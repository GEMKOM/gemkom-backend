"""
Job order cancellation service.

Handles all side-effects when a job order is cancelled:
  1. Cancel open PurchaseRequests that contain items for this job
  2. Cancel / delete PlanningRequestItems for this job (cancel whole
     PlanningRequest if it becomes empty)
  3. Auto-close open NCRs linked to this job
  4. Cancel pending QCReviews (and their open approval workflows)
  5. Cancel open ExpectedReceipts linked to this job
  6. Retire SubcontractingAssignments on the job's tasks
  7. Delete SubcontractorCostRecalcQueue entry for this job
  8. Cascade status on the JobOrder itself, children, and department tasks
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone


def cancel_job_order(job_order, user=None):
    """
    Cancel *job_order* and clean up all dependent open records.

    Raises ValueError if the job is already completed.
    DB writes run inside a single atomic transaction; the notification
    to the job creator is dispatched after commit.
    """
    if job_order.status == 'completed':
        raise ValueError("Tamamlanmış işler iptal edilemez.")

    if job_order.status == 'cancelled':
        return  # idempotent

    # Capture creator before the transaction so it's available post-commit.
    creator = job_order.created_by

    with transaction.atomic():
        _cancel_purchase_requests(job_order, user)
        _cancel_planning_request_items(job_order)
        _close_ncrs(job_order)
        _cancel_qc_reviews(job_order)
        _cancel_expected_receipts(job_order)
        _retire_subcontracting_assignments(job_order)
        _drain_subcontractor_recalc_queue(job_order)
        _cancel_job_and_cascade(job_order, user)

        transaction.on_commit(lambda: _notify_job_cancelled(job_order, creator, user))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cancel_purchase_requests(job_order, user):
    """Cancel every non-cancelled PR that has at least one item for this job."""
    from planning.models import PlanningRequestItem
    from procurement.models import PurchaseRequest
    from procurement.services import cancel_purchase_request

    pr_ids = (
        PlanningRequestItem.objects
        .filter(job_no=job_order.job_no)
        .values_list('purchase_requests__id', flat=True)
        .distinct()
    )
    prs = PurchaseRequest.objects.filter(
        id__in=pr_ids,
    ).exclude(status__in=['cancelled', 'rejected'])

    system_user = user or _get_system_user()
    for pr in prs:
        cancel_purchase_request(pr, by_user=system_user, reason=f'İş emri iptal edildi: {job_order.job_no}')


def _cancel_planning_request_items(job_order):
    """
    Delete PlanningRequestItems for this job that are still in open planning
    requests (not yet converted/completed/cancelled).  If deletion empties a
    planning request, cancel that request too.
    """
    from planning.models import PlanningRequest, PlanningRequestItem

    open_statuses = ['pending_inventory', 'pending_erp_entry', 'ready']

    items = PlanningRequestItem.objects.filter(
        job_no=job_order.job_no,
        planning_request__status__in=open_statuses,
    ).select_related('planning_request')

    affected_pr_ids = set(items.values_list('planning_request_id', flat=True))
    items.delete()

    # Cancel any planning request that is now empty
    for pr in PlanningRequest.objects.filter(id__in=affected_pr_ids, status__in=open_statuses):
        if not pr.items.exists():
            pr.status = 'cancelled'
            pr.save(update_fields=['status'])


def _close_ncrs(job_order):
    """Auto-close NCRs in draft / submitted / approved state."""
    from quality_control.models import NCR
    from approvals.models import ApprovalWorkflow
    from django.contrib.contenttypes.models import ContentType

    open_ncrs = job_order.ncrs.exclude(status__in=['closed', 'rejected'])
    if not open_ncrs.exists():
        return

    ncr_ct = ContentType.objects.get_for_model(NCR)
    ncr_ids = list(open_ncrs.values_list('id', flat=True))

    # Cancel any live approval workflows on these NCRs
    ApprovalWorkflow.objects.filter(
        content_type=ncr_ct,
        object_id__in=ncr_ids,
        is_complete=False,
        is_rejected=False,
        is_cancelled=False,
    ).update(is_cancelled=True, cancelled_at=timezone.now())

    open_ncrs.update(status='closed')


def _cancel_qc_reviews(job_order):
    """Cancel pending QCReviews across all tasks of this job."""
    from quality_control.models import QCReview
    from approvals.models import ApprovalWorkflow
    from django.contrib.contenttypes.models import ContentType

    pending_reviews = QCReview.objects.filter(
        task__job_order=job_order,
        status='pending',
    )
    if not pending_reviews.exists():
        return

    review_ct = ContentType.objects.get_for_model(QCReview)
    review_ids = list(pending_reviews.values_list('id', flat=True))

    ApprovalWorkflow.objects.filter(
        content_type=review_ct,
        object_id__in=review_ids,
        is_complete=False,
        is_rejected=False,
        is_cancelled=False,
    ).update(is_cancelled=True, cancelled_at=timezone.now())

    pending_reviews.update(status='rejected', reviewed_at=timezone.now())


def _cancel_expected_receipts(job_order):
    """Cancel open expected receipts linked to this job."""
    job_order.expected_receipts.filter(status='expected').update(status='cancelled')


def _retire_subcontracting_assignments(job_order):
    """Mark subcontracting assignments on this job's tasks as retired."""
    from subcontracting.models import SubcontractingAssignment

    SubcontractingAssignment.objects.filter(
        department_task__job_order=job_order,
        is_retired=False,
    ).update(is_retired=True)


def _drain_subcontractor_recalc_queue(job_order):
    """Remove any stale background recalc queue entry for this job."""
    from subcontracting.models import SubcontractorCostRecalcQueue

    SubcontractorCostRecalcQueue.objects.filter(job_no=job_order.job_no).delete()


def _cancel_job_and_cascade(job_order, user):
    """Set the job, its children, and open department tasks to cancelled."""
    job_order.status = 'cancelled'
    job_order.save(update_fields=['status'])

    for child in job_order.children.exclude(status='completed'):
        # Recurse: each child triggers its own full cancellation
        cancel_job_order(child, user=user)

    job_order.department_tasks.exclude(
        status__in=['completed', 'skipped']
    ).update(status='cancelled')


def _get_system_user():
    from django.contrib.auth.models import User
    return User.objects.filter(username='system').first()


def _notify_job_cancelled(job_order, creator, cancelled_by):
    from notifications.service import notify, bulk_notify, render_notification, get_route_users
    from notifications.models import Notification

    actor_name = (
        cancelled_by.get_full_name() or cancelled_by.username
        if cancelled_by else 'Sistem'
    )
    ctx = {
        'job_no':    job_order.job_no,
        'job_title': job_order.title,
        'actor':     actor_name,
    }
    title, body, link = render_notification(Notification.JOB_CANCELLED, ctx)

    kwargs = dict(
        notification_type=Notification.JOB_CANCELLED,
        title=title,
        body=body,
        link=link,
        source_type='job_order',
        source_id=job_order.job_no,
    )

    # Always notify the job creator.
    if creator:
        notify(user=creator, **kwargs)

    # Also notify any users/groups configured via NotificationConfig routing.
    route_users = get_route_users(Notification.JOB_CANCELLED)
    if creator:
        route_users = route_users.exclude(pk=creator.pk)
    if route_users.exists():
        bulk_notify(users=route_users, **kwargs)
