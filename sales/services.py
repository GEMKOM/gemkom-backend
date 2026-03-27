"""
Sales services: offer number generation, consultation dispatch,
price revision management, approval integration, and offer-to-job-order conversion.
"""
from __future__ import annotations

import re
from collections import defaultdict

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from notifications.service import bulk_notify, get_route, render_notification
from notifications.models import Notification
from projects.models import JobOrder, JobOrderDepartmentTask, JobOrderDiscussionTopic

from .models import (
    SalesOffer,
    SalesOfferItem,
    SalesOfferFile,
    SalesOfferPriceRevision,
    OfferTemplateNode,
)


# =============================================================================
# Reference number generators
# =============================================================================

def generate_offer_no(year: int) -> str:
    """
    Thread-safe offer number generator.
    Format: OF-{year}-{seq:04d}
    Uses SELECT FOR UPDATE on the last record to prevent race conditions.
    """
    with transaction.atomic():
        last = (
            SalesOffer.objects
            .select_for_update()
            .filter(offer_no__startswith=f'OF-{year}-')
            .order_by('-offer_no')
            .first()
        )
        if last:
            try:
                seq = int(last.offer_no.split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1
        return f'OF-{year}-{seq:04d}'


def generate_job_no(customer_code: str, parent_job_no: str = None) -> str:
    """
    Thread-safe job number generator.
    Must be called inside an existing atomic block (select_for_update requires one).

    Top-level: {customer_code}-{seq:02d}   e.g. "253-01"
    Child:     {parent_job_no}-{seq:02d}   e.g. "253-01-02"
    """
    if parent_job_no:
        siblings = (
            JobOrder.objects
            .select_for_update()
            .filter(parent__job_no=parent_job_no)
            .order_by('-job_no')
        )
        if siblings.exists():
            try:
                seq = int(siblings.first().job_no.split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1
        return f'{parent_job_no}-{seq:02d}'
    else:
        roots = (
            JobOrder.objects
            .select_for_update()
            .filter(customer__code=customer_code, parent__isnull=True)
            .order_by('-job_no')
        )
        if roots.exists():
            # Parse the numeric segment after the customer code prefix
            try:
                last_no = roots.first().job_no
                # job_no like "RM243-01" or "253-01"
                parts = last_no.split('-')
                seq = int(parts[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1
        return f'{customer_code}-{seq:02d}'


# =============================================================================
# Consultation dispatch
# =============================================================================

def send_consultations(offer: SalesOffer, departments_data: list[dict], user) -> list:
    """
    Create JobOrderDepartmentTask records for simultaneous department consultations.

    departments_data items:
        {
            'department': str,           # required — e.g. 'design'
            'assigned_to': int | None,   # user pk
            'title': str,                # consultation title
            'notes': str,                # request notes → task description
            'deadline': date | None,     # target_completion_date
            'file_ids': list[int],       # SalesOfferFile PKs to share
        }

    Returns list of created JobOrderDepartmentTask instances.
    Raises ValueError if any requested department already has a consultation task (any status).
    """
    with transaction.atomic():
        requested_departments = [dept['department'] for dept in departments_data]

        conflicts = (
            offer.department_tasks
            .filter(department__in=requested_departments)
            .values_list('department', flat=True)
        )
        if conflicts:
            dept_labels = ', '.join(sorted(set(conflicts)))
            raise ValueError(
                f"Bu departmanlar için zaten bir danışma görevi mevcut: {dept_labels}. "
                "Mevcut görevi güncelleyin veya iptal edin."
            )

        created = []
        for dept in departments_data:
            task = JobOrderDepartmentTask.objects.create(
                sales_offer=offer,
                job_order=None,
                department=dept['department'],
                task_type='sales_consult',
                title=dept.get('title') or f"Danışma: {offer.offer_no}",
                description=dept.get('notes', ''),
                assigned_to_id=dept.get('assigned_to'),
                target_completion_date=dept.get('deadline') or offer.offer_expiry_date,
                status='pending',
                created_by=user,
            )

            file_ids = dept.get('file_ids') or []
            if file_ids:
                task.shared_files.set(
                    offer.files.filter(id__in=file_ids)
                )

            JobOrderDiscussionTopic.objects.create(
                task=task,
                job_order=None,
                title=f'Danışmanlık: {task.title}',
                content='',
                topic_type='general',
                priority='normal',
                created_by=user,
            )

            created.append(task)

        if offer.status == 'draft':
            offer.status = 'consultation'
            offer.save(update_fields=['status', 'updated_at'])

        transaction.on_commit(lambda tasks=list(created): _notify_dept_heads_on_consultation(offer, tasks))

        return created


# =============================================================================
# Email notifications
# =============================================================================

def _notify_approvers_on_submission(offer: SalesOffer, wf):
    """Notify all approvers in the first stage when an offer is submitted for approval."""
    from approvals.models import ApprovalStageInstance
    try:
        stage = ApprovalStageInstance.objects.filter(workflow=wf, order=wf.current_stage_order).first()
        if not stage:
            return
        approver_ids = list(stage.approver_user_ids or [])
        approvers = User.objects.filter(id__in=approver_ids, is_active=True)
        if not approvers.exists():
            return
        ctx = {
            'offer_no':    offer.offer_no,
            'offer_title': offer.title,
            'customer':    offer.customer.name,
            'total_price': str(offer.total_price),
        }
        title, body, link = render_notification(Notification.SALES_APPROVAL_REQUESTED, ctx)
        bulk_notify(
            users=approvers,
            notification_type=Notification.SALES_APPROVAL_REQUESTED,
            title=title,
            body=body,
            link=link,
            source_type='sales_offer',
            source_id=offer.id,
        )
    except Exception:
        pass


def _notify_departments_on_conversion(offer: SalesOffer, root_job):
    """Notify route-configured users when an offer is converted to a job order."""
    try:
        users, link = get_route(Notification.SALES_CONVERTED)
        if not users.exists():
            return
        ctx = {
            'offer_no':    offer.offer_no,
            'offer_title': offer.title,
            'customer':    offer.customer.name,
            'job_no':      root_job.job_no,
            'job_title':   root_job.title,
        }
        title, body, link = render_notification(Notification.SALES_CONVERTED, ctx, link)
        bulk_notify(
            users=users,
            notification_type=Notification.SALES_CONVERTED,
            title=title,
            body=body,
            link=link,
            source_type='job_order',
            source_id=root_job.job_no,
        )
    except Exception:
        pass


def _notify_dept_heads_on_consultation(offer: SalesOffer, tasks: list):
    """
    Send one notification per consultation task to:
      - The department's managers (users with occupation='manager' in that team)
      - The explicitly assigned user (if any)
      - Route-configured global watchers
    """
    try:
        from django.contrib.auth.models import User as DjangoUser
        from users.helpers import _team_manager_user_ids
        route_users, route_link = get_route(Notification.SALES_CONSULTATION)
        route_ids = set(route_users.values_list('id', flat=True))

        for task in tasks:
            ctx = {
                'offer_no':        offer.offer_no,
                'offer_title':     offer.title,
                'customer':        offer.customer.name,
                'department':      task.get_department_display(),
                'department_code': task.department,
                'task_id':         task.id,
                'task_title':      task.title,
                'notes':           task.description or '',
            }
            title, body, link = render_notification(Notification.SALES_CONSULTATION, ctx, route_link)

            manager_ids = set(_team_manager_user_ids(task.department))
            recipient_ids = manager_ids | route_ids
            if task.assigned_to_id:
                recipient_ids.add(task.assigned_to_id)
            if not recipient_ids:
                continue

            users = DjangoUser.objects.filter(id__in=recipient_ids, is_active=True)
            bulk_notify(
                users=users,
                notification_type=Notification.SALES_CONSULTATION,
                title=title,
                body=body,
                link=link,
                source_type='sales_offer',
                source_id=offer.id,
            )
    except Exception:
        pass


# =============================================================================
# Approval workflow
# =============================================================================

SALES_OFFER_POLICY_NAME = "Satış Teklif Onayı"


def _get_sales_offer_policy():
    from approvals.models import ApprovalPolicy
    policy = (
        ApprovalPolicy.objects
        .filter(is_active=True, name=SALES_OFFER_POLICY_NAME)
        .order_by('selection_priority')
        .first()
    )
    if not policy:
        raise ValueError(
            f"'{SALES_OFFER_POLICY_NAME}' adlı aktif onay politikası bulunamadı. "
            "Lütfen yönetici panelinden politikayı oluşturun."
        )
    return policy


def rollback_to_pricing(offer: SalesOffer) -> None:
    """
    Cancel any active approval workflow and move the offer back to 'pricing'.
    Called when items are added/edited/deleted after submission or approval.
    """
    from django.contrib.contenttypes.models import ContentType
    from approvals.models import ApprovalWorkflow
    ct = ContentType.objects.get_for_model(SalesOffer)
    ApprovalWorkflow.objects.filter(
        content_type=ct,
        object_id=offer.id,
        is_complete=False,
        is_rejected=False,
    ).update(is_rejected=True)
    offer.status = 'pricing'
    offer.save(update_fields=['status', 'updated_at'])


def submit_for_approval(offer: SalesOffer, user):
    """
    Submit the offer for internal approval.
    Auto-calculates total price from item unit_prices (EUR).
    Auto-selects the policy by name.
    Increments offer.approval_round.
    Returns the created ApprovalWorkflow.
    """
    from decimal import Decimal
    from approvals.services import create_workflow, auto_bypass_self_approver

    with transaction.atomic():
        total = offer.total_price
        if total == Decimal('0.00'):
            raise ValueError(
                "Onaya göndermeden önce en az bir kaleme fiyat girilmelidir."
            )

        is_initial = not offer.price_revisions.exists()
        revision_type = 'initial' if is_initial else 'sales_revision'

        offer.price_revisions.filter(is_current=True).update(is_current=False)
        SalesOfferPriceRevision.objects.create(
            offer=offer,
            revision_type=revision_type,
            amount=total,
            currency='EUR',
            approval_round=offer.approval_round + 1,
            is_current=True,
            created_by=user,
        )

        policy = _get_sales_offer_policy()

        # Cancel any stale active workflows before creating a new one
        from django.contrib.contenttypes.models import ContentType
        from approvals.models import ApprovalWorkflow
        ct = ContentType.objects.get_for_model(SalesOffer)
        ApprovalWorkflow.objects.filter(
            content_type=ct,
            object_id=offer.id,
            is_complete=False,
            is_rejected=False,
        ).update(is_rejected=True)

        offer.approval_round += 1
        offer.status = 'pending_approval'
        offer.save(update_fields=['approval_round', 'status', 'updated_at'])

        snapshot = {
            'offer_no': offer.offer_no,
            'amount': str(total),
            'currency': 'EUR',
            'round': offer.approval_round,
        }

        wf = create_workflow(subject=offer, policy=policy, snapshot=snapshot)
        auto_bypass_self_approver(wf, user.id)

        transaction.on_commit(lambda: _notify_approvers_on_submission(offer, wf))
        return wf


def record_approval_decision(
    offer: SalesOffer,
    approver,
    approve: bool,
    comment: str = '',
    counter_amount=None,
    counter_currency: str = '',
) -> dict:
    """
    Approve or reject the current approval workflow stage.

    If rejected and counter_amount is provided, creates an 'approver_counter'
    SalesOfferPriceRevision (is_current=False) so the sales person can see
    the approver's suggested price.

    If approved (outcome='completed'), marks the current price revision as
    revision_type='approved'.

    Returns {'outcome': str, 'workflow': ApprovalWorkflow}.
    """
    from approvals.services import record_decision

    wf, stage, outcome = record_decision(offer, approver, approve, comment)

    if outcome == 'rejected' and counter_amount is not None:
        SalesOfferPriceRevision.objects.create(
            offer=offer,
            revision_type='approver_counter',
            amount=counter_amount,
            currency=counter_currency or 'EUR',
            notes=comment,
            approval_round=offer.approval_round,
            is_current=False,
            created_by=approver,
        )

    if outcome == 'completed':
        # handle_approval_event on SalesOffer sets status='approved'.
        # Also mark current price revision as the approved one.
        offer.price_revisions.filter(is_current=True).update(revision_type='approved')

    return {'outcome': outcome, 'workflow': wf}


# =============================================================================
# Offer → Job Order conversion
# =============================================================================

def _create_job_from_item(item: SalesOfferItem, parent_job, children_map: dict, offer: SalesOffer, user, incoterms: str, file_ids: list) -> JobOrder:
    """
    Recursively create a JobOrder for the given SalesOfferItem.
    children_map: {template_node_id -> [child SalesOfferItem, ...]}
    file_ids: SalesOfferFile PKs to attach (reference only) to root-level jobs.
    """
    title = item.resolved_title or offer.title

    parent_job_no = parent_job.job_no if parent_job else None
    job_no = generate_job_no(offer.customer.code, parent_job_no)

    job = JobOrder.objects.create(
        job_no=job_no,
        title=title,
        customer=offer.customer,
        quantity=item.quantity,
        parent=parent_job,
        source_offer=offer,
        description=offer.description if not parent_job else '',
        customer_order_no=offer.customer_inquiry_ref or '',
        target_completion_date=offer.delivery_date_requested,
        incoterms=incoterms or '',
        status='draft',
        created_by=user,
    )

    # Attach offer files to root-level jobs only
    if not parent_job and file_ids:
        job.offer_files.set(offer.files.filter(id__in=file_ids))

    # Recurse into selected children
    node_id = item.template_node_id
    for child_item in sorted(children_map.get(node_id, []), key=lambda i: i.sequence):
        _create_job_from_item(child_item, job, children_map, offer, user, incoterms, file_ids)

    return job


def _get_effective_parent_item(node: OfferTemplateNode, selected_node_ids: set, item_by_node_id: dict):
    """
    Walk up the template tree to find the nearest ancestor that is also selected.
    Returns the SalesOfferItem for that ancestor, or None if this item is a root.
    """
    current = node.parent
    while current:
        if current.id in selected_node_ids:
            return item_by_node_id[current.id]
        # Walk up further — need to load the parent
        current = current.parent
    return None


@transaction.atomic
def convert_offer_to_job_order(offer: SalesOffer, user, file_ids: list = None) -> JobOrder:
    """
    Convert a SalesOffer into one or more JobOrders.

    Uses the "effective parent" algorithm to reconstruct job order hierarchy
    from the selected items (gaps in the template tree are skipped).
    Each root item (no selected ancestor) → top-level job order.
    Each non-root item → child of its nearest selected ancestor's job order.

    file_ids: SalesOfferFile PKs to attach (by reference) to root job orders.

    Sets offer.status='won', offer.converted_job_order, offer.won_at.
    Returns the first/primary root job order.
    """
    if offer.status not in ('approved', 'submitted_customer', 'won'):
        raise ValueError(
            "Teklif onaylanmadan veya müşteriye sunulmadan iş emrine dönüştürülemez."
        )

    if offer.converted_job_order_id:
        raise ValueError("Bu teklif zaten bir iş emrine dönüştürülmüştür.")

    incoterms = offer.incoterms or ''

    # Load all items, pre-fetching the full parent chain for effective-parent traversal
    items = list(
        offer.items
        .select_related(
            'template_node__parent__parent__parent'  # covers up to 4 levels deep
        )
        .order_by('sequence')
    )

    if not items:
        raise ValueError(
            "İş emri oluşturmak için teklifte en az bir kalem bulunmalıdır."
        )

    file_ids = file_ids or []

    # Build effective parent map
    selected_node_ids = {
        item.template_node_id
        for item in items
        if item.template_node_id
    }
    item_by_node_id = {
        item.template_node_id: item
        for item in items
        if item.template_node_id
    }

    roots = []          # true top-level catalog nodes (template_node.parent is None)
    orphaned = []       # nested catalog nodes or custom items whose catalog parent was not selected
    children_map = defaultdict(list)  # parent_node_id → [child SalesOfferItems]

    for item in items:
        if not item.template_node_id:
            # Custom item (no catalog node) → group with orphaned
            orphaned.append(item)
            continue

        eff_parent = _get_effective_parent_item(
            item.template_node, selected_node_ids, item_by_node_id
        )
        if eff_parent is None:
            # No selected ancestor — check if this is a true top-level node
            if item.template_node.parent_id is None:
                roots.append(item)
            else:
                # Nested catalog item whose parent was not selected
                orphaned.append(item)
        else:
            children_map[eff_parent.template_node_id].append(item)

    # If there are multiple orphaned items (nested catalog nodes whose catalog parent
    # was not selected, or custom items), group them under a single wrapper job
    # named after the offer. A single orphaned item becomes its own top-level job.
    first_root_job = None

    if len(orphaned) > 1:
        wrapper_job_no = generate_job_no(offer.customer.code, None)
        wrapper_job = JobOrder.objects.create(
            job_no=wrapper_job_no,
            title=offer.title,
            customer=offer.customer,
            quantity=1,
            parent=None,
            source_offer=offer,
            description=offer.description,
            customer_order_no=offer.customer_inquiry_ref or '',
            target_completion_date=offer.delivery_date_requested,
            incoterms=incoterms or '',
            status='draft',
            created_by=user,
        )
        if file_ids:
            wrapper_job.offer_files.set(offer.files.filter(id__in=file_ids))
        for orphan_item in orphaned:
            _create_job_from_item(orphan_item, wrapper_job, children_map, offer, user, incoterms, [])
        first_root_job = wrapper_job
    else:
        for orphan_item in orphaned:
            job = _create_job_from_item(orphan_item, None, children_map, offer, user, incoterms, file_ids)
            if first_root_job is None:
                first_root_job = job

    for root_item in roots:
        job = _create_job_from_item(root_item, None, children_map, offer, user, incoterms, file_ids)
        if first_root_job is None:
            first_root_job = job

    # Update offer
    offer.status = 'converted'
    offer.converted_job_order = first_root_job
    offer.won_at = timezone.now()
    offer.save(update_fields=['status', 'converted_job_order', 'won_at', 'updated_at'])

    transaction.on_commit(lambda: _notify_departments_on_conversion(offer, first_root_job))
    return first_root_job
