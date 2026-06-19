"""
Production / delivery phase support for job orders.

Planning can split an engineering job order (e.g. 270-01) into delivery phases.
Each phase is a *phase node* — a child JobOrder named ``{root}/P{n}`` that acts as
a delivery batch container (it carries the delivery date, shipping docs, status,
and is the thing you "activate"). Under each phase node sit *allocations* —
``{product}/P{n}`` job orders that carry the quantity of a given product master
scheduled for that phase.

Hierarchy created for 270-01 (3 phases)::

    270-01                         (engineering root; rolls up from phases only)
      270-01-01 .. 270-01-16       (product masters — kept, hold drawings/design;
                                     excluded from roll-up once phased)
      270-01/P1                    (phase node; source_job_order = 270-01)
        270-01-01/P1   qty 1       (allocation; source_job_order = 270-01-01)
        270-01-06/P1   qty 2
      270-01/P2
        270-01-01/P2   qty 1
        ...

Roll-up stays correct because :meth:`JobOrder._aggregatable_children` excludes the
phased masters: the root averages its phase nodes, each phase node averages its
allocations.
"""
from django.db import transaction

from projects.models import JobOrder


def _normalize_quantities(raw, valid_phase_numbers):
    """
    Turn a {phase_number: qty} mapping (keys may be str or int) into a clean
    {int phase_number: int qty} dict, validating against *valid_phase_numbers*.
    """
    cleaned = {}
    for key, value in (raw or {}).items():
        try:
            pn = int(key)
            qty = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Geçersiz miktar değeri: faz {key} = {value}")
        if pn not in valid_phase_numbers:
            raise ValueError(f"Tanımsız faz numarasına atama yapılamaz: P{pn}")
        if qty < 0:
            raise ValueError("Miktarlar negatif olamaz.")
        if qty:
            cleaned[pn] = qty
    return cleaned


@transaction.atomic
def create_phases(source_root_job, phases, allocations, user=None):
    """
    Split an engineering job order into delivery phases with per-product quantities.

    Args:
        source_root_job: the engineering :class:`JobOrder` to split.
        phases: list of dicts describing each phase node. Recognised keys:
            ``phase_number`` (required, positive int), ``title``,
            ``target_completion_date``, ``priority``.
        allocations: list of dicts, one per product master to phase::
            {"product_job_no": "270-01-01", "quantities": {1: 1, 2: 1}}
            For every listed product the quantities must sum **exactly** to the
            master's quantity.
        user: the user performing the split (recorded as created_by).

    Returns:
        list of the created phase-node :class:`JobOrder` instances.
    """
    if source_root_job.is_phase_job:
        raise ValueError("Bir faz iş emri yeniden fazlara bölünemez.")
    if not phases:
        raise ValueError("En az bir faz tanımlanmalıdır.")
    if not allocations:
        raise ValueError("En az bir ürün için miktar ataması yapılmalıdır.")

    # --- Validate phase specs ---
    phase_numbers = []
    for idx, spec in enumerate(phases, start=1):
        pn = spec.get('phase_number') or idx
        try:
            pn = int(pn)
        except (TypeError, ValueError):
            raise ValueError(f"Geçersiz faz numarası: {spec.get('phase_number')}")
        if pn < 1:
            raise ValueError("Faz numarası 1 veya daha büyük olmalıdır.")
        if pn in phase_numbers:
            raise ValueError(f"Faz {pn} birden fazla kez tanımlanmış.")
        phase_numbers.append(pn)
    phase_number_set = set(phase_numbers)

    if source_root_job.phase_mirrors.filter(phase_number__in=phase_numbers).exists():
        raise ValueError("Bu iş emri için belirtilen fazlardan bazıları zaten mevcut.")

    # --- Validate allocations against the product masters ---
    masters = {
        jo.job_no: jo
        for jo in source_root_job.children.filter(source_job_order__isnull=True)
    }

    # phase_number -> {product_job_no: qty}
    plan = {pn: {} for pn in phase_numbers}
    for alloc in allocations:
        product_no = alloc.get('product_job_no')
        master = masters.get(product_no)
        if master is None:
            raise ValueError(f"'{product_no}' bu iş emrinin bir ürün alt işi değil.")

        quantities = _normalize_quantities(alloc.get('quantities'), phase_number_set)
        if not quantities:
            # Product not allocated to any phase — skip it (stays unphased).
            continue

        total = sum(quantities.values())
        if total != master.quantity:
            raise ValueError(
                f"'{product_no}' için faz miktarları toplamı ({total}) "
                f"ürün miktarına ({master.quantity}) eşit olmalıdır."
            )
        for pn, qty in quantities.items():
            plan[pn][product_no] = qty

    if not any(plan.values()):
        raise ValueError("Hiçbir ürün için geçerli bir faz miktarı girilmedi.")

    # --- Create phase nodes and their allocations ---
    spec_by_number = {}
    for idx, spec in enumerate(phases, start=1):
        spec_by_number[int(spec.get('phase_number') or idx)] = spec

    created = []
    for pn in phase_numbers:
        spec = spec_by_number[pn]
        phase_node = JobOrder.objects.create(
            job_no=f"{source_root_job.job_no}/P{pn}",
            parent=source_root_job,
            source_job_order=source_root_job,
            phase_number=pn,
            title=spec.get('title') or f"{source_root_job.title} - Faz {pn}",
            customer=source_root_job.customer,
            customer_order_no=source_root_job.customer_order_no,
            priority=spec.get('priority') or source_root_job.priority,
            target_completion_date=spec.get('target_completion_date'),
            incoterms=source_root_job.incoterms,
            status='draft',
            created_by=user,
        )

        for product_no, qty in plan[pn].items():
            master = masters[product_no]
            JobOrder.objects.create(
                job_no=f"{product_no}/P{pn}",
                parent=phase_node,
                source_job_order=master,
                phase_number=pn,
                title=master.title,
                quantity=qty,
                customer=master.customer,
                customer_order_no=master.customer_order_no,
                priority=master.priority,
                target_completion_date=spec.get('target_completion_date'),
                incoterms=master.incoterms,
                source_offer_id=master.source_offer_id,
                source_offer_item_id=master.source_offer_item_id,
                template_node_id=master.template_node_id,
                status='draft',
                created_by=user,
            )

        created.append(phase_node)

    # Refresh the root roll-up now that masters are excluded and phases exist.
    source_root_job.update_completion_percentage()

    return created


def activate_phase(phase_root_job, user=None):
    """
    Activate a delivery phase node. Delegates to :meth:`JobOrder.start`, which
    moves the phase from draft to active and cascades to its allocations.
    """
    if not phase_root_job.is_phase_job:
        raise ValueError("Bu iş emri bir üretim fazı değil.")
    if phase_root_job.status != 'draft':
        raise ValueError("Sadece taslak durumundaki fazlar etkinleştirilebilir.")
    phase_root_job.start(user=user)
    return phase_root_job
