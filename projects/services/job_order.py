"""
Service functions for JobOrder mutations that require coordinated updates
across multiple tables (job_no rename, customer cascade).
"""

from django.db import connection, transaction


def rename_job_no(old_job_no: str, new_job_no: str) -> None:
    """
    Rename a job order's primary key and update every reference to it.

    FK references inside the projects app cascade automatically via
    ON UPDATE CASCADE (added by migration 0038).

    CharField references across other apps are updated with raw SQL.

    Children are renamed level-by-level (parents before children) so the
    parent FK constraint is always satisfied during the cascade.
    """
    with transaction.atomic():
        # Collect all descendants sorted by depth (shallowest first).
        # Suffix always starts with a dash, e.g. "OLD-01", "OLD-01-02".
        from projects.models import JobOrder

        descendants = list(
            JobOrder.objects
            .filter(job_no__startswith=old_job_no + '-')
            .order_by('job_no')   # lexicographic == depth-order for this scheme
            .values_list('job_no', flat=True)
        )

        # Rename the root first.  ON UPDATE CASCADE propagates the change to
        # every FK column inside the projects app (including parent_id on child
        # job orders).  CharField refs in other apps are then patched per table.
        _rename_single(old_job_no, new_job_no)

        # Rename each descendant (parent already has its new job_no now).
        for old_child_no in descendants:
            new_child_no = new_job_no + old_child_no[len(old_job_no):]
            _rename_single(old_child_no, new_child_no)


def _rename_single(old_no: str, new_no: str) -> None:
    """Update the PK and all cross-app CharField references for one job order."""
    with connection.cursor() as cur:
        # 1. Update the primary key.
        #    ON UPDATE CASCADE handles all FK columns inside projects app.
        cur.execute(
            "UPDATE projects_joborder SET job_no = %s WHERE job_no = %s",
            [new_no, old_no],
        )

        # 2. Cross-app CharField references (denormalised, no DB-level FK).
        _bulk_update(cur, [
            # (table, column)
            ('tasks_part',                               'job_no'),
            ('tasks_partcostagg',                        'job_no_cached'),
            ('tasks_partcostaguser',                     'job_no_cached'),
            ('cnc_cutting_cncpart',                      'job_no'),
            ('machining_task',                           'job_no'),
            ('planning_planningrequestitem',             'job_no'),
            ('procurement_purchaserequestitemallocation', 'job_no'),
            ('procurement_purchaseorderlineallocation',  'job_no'),
            ('subcontracting_subcontractorstatementline', 'job_no'),
            ('welding_time_entry',                       'job_no'),
            ('welding_job_cost_agg_user',                'job_no'),
            ('overtime_overtimeentry',                   'job_no'),
            # Notification source_id stores job_no as a generic string PK
            ('notifications_notification',              'source_id'),
        ], old_no, new_no)

        # 3. Tables where job_no is itself the PK — update carefully.
        #    These are small queue/aggregate tables; no other table references them.
        for table in (
            'subcontracting_cost_recalc_queue',
            'welding_job_cost_agg',
            'welding_job_cost_recalc_queue',
        ):
            cur.execute(
                f"UPDATE {table} SET job_no = %s WHERE job_no = %s",  # noqa: S608
                [new_no, old_no],
            )


def _bulk_update(cur, tables_cols, old_val, new_val):
    for table, col in tables_cols:
        cur.execute(
            f"UPDATE {table} SET {col} = %s WHERE {col} = %s",  # noqa: S608
            [new_val, old_val],
        )


def cascade_customer_to_children(job_order) -> None:
    """
    Propagate a parent job order's customer to all its descendants.
    Called after saving a root job order with a new customer.
    """
    from projects.models import JobOrder

    descendants = JobOrder.objects.filter(
        job_no__startswith=job_order.job_no + '-'
    )
    descendants.update(customer=job_order.customer)
