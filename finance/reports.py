from __future__ import annotations
from calendar import monthrange
from datetime import date
from decimal import Decimal

from procurement.reports.common import q2, get_fallback_rates, to_eur
from .services import compute_monthly_wage, expense_applies_to_month


def build_finance_outflow_detail(month: str) -> dict:
    """
    All finance-side outflows for a given month (YYYY-MM):
    wages, monthly expenses, loan installments, tax entries, ad-hoc job costs.
    """
    try:
        year, mon = map(int, month.split("-"))
    except (ValueError, AttributeError):
        return {}

    from .models import MonthlyExpense, LoanInstallment, TaxEntry, AdHocJobCost

    fb = get_fallback_rates()

    # --- Wages ---
    wages = compute_monthly_wage(year, mon)

    # --- Monthly Expenses ---
    active_expenses = MonthlyExpense.objects.filter(status="active")
    expenses_rows = []
    expenses_total = Decimal("0.00")
    for exp in active_expenses:
        if not expense_applies_to_month(exp, year, mon):
            continue
        amt_eur = to_eur(exp.amount, exp.currency, {}, fb) or Decimal("0")
        expenses_total += amt_eur
        expenses_rows.append({
            "id": exp.id,
            "category": exp.category,
            "description": exp.description,
            "amount": str(q2(exp.amount)),
            "currency": exp.currency,
            "recurrence": exp.recurrence,
            "amount_eur": str(q2(amt_eur)),
        })

    # --- Loan Installments ---
    loan_installments = (
        LoanInstallment.objects
        .filter(due_date__year=year, due_date__month=mon)
        .select_related("loan")
        .exclude(loan__status="cancelled")
    )
    loans_rows = []
    loans_total = Decimal("0.00")
    for inst in loan_installments:
        amt_eur = to_eur(inst.total_payment, inst.loan.currency, {}, fb) or Decimal("0")
        loans_total += amt_eur
        loans_rows.append({
            "loan_id": inst.loan_id,
            "loan_name": inst.loan.name,
            "installment_id": inst.id,
            "sequence": inst.sequence,
            "due_date": inst.due_date.isoformat(),
            "principal": str(q2(inst.principal_component)),
            "interest": str(q2(inst.interest_component)),
            "total": str(q2(inst.total_payment)),
            "currency": inst.loan.currency,
            "total_eur": str(q2(amt_eur)),
            "is_paid": inst.is_paid,
            "paid_at": inst.paid_at.date().isoformat() if inst.paid_at else None,
        })

    # --- Tax Entries ---
    taxes = TaxEntry.objects.filter(due_date__year=year, due_date__month=mon)
    taxes_rows = []
    taxes_total = Decimal("0.00")
    for tax in taxes:
        amt_eur = to_eur(tax.amount, tax.currency, {}, fb) or Decimal("0")
        taxes_total += amt_eur
        taxes_rows.append({
            "id": tax.id,
            "tax_type": tax.tax_type,
            "period_label": tax.period_label,
            "description": tax.description,
            "amount": str(q2(tax.amount)),
            "currency": tax.currency,
            "due_date": tax.due_date.isoformat(),
            "amount_eur": str(q2(amt_eur)),
            "is_paid": tax.is_paid,
            "paid_at": tax.paid_at.date().isoformat() if tax.paid_at else None,
        })

    # --- Ad-hoc Job Costs ---
    adhoc = (
        AdHocJobCost.objects
        .filter(cost_date__year=year, cost_date__month=mon)
        .select_related("job_order")
    )
    adhoc_rows = []
    adhoc_total = Decimal("0.00")
    for cost in adhoc:
        amt_eur = to_eur(cost.amount, cost.currency, {}, fb) or Decimal("0")
        adhoc_total += amt_eur
        adhoc_rows.append({
            "id": cost.id,
            "job_no": cost.job_order_id,
            "job_title": cost.job_order.title if cost.job_order else None,
            "description": cost.description,
            "category": cost.category,
            "amount": str(q2(cost.amount)),
            "currency": cost.currency,
            "cost_date": cost.cost_date.isoformat(),
            "amount_eur": str(q2(amt_eur)),
        })

    wages_eur = Decimal(wages["total_eur"])
    grand_total = wages_eur + expenses_total + loans_total + taxes_total + adhoc_total

    return {
        "wages": wages,
        "expenses": expenses_rows,
        "loans": loans_rows,
        "taxes": taxes_rows,
        "adhoc_costs": adhoc_rows,
        "totals": {
            "wages_eur": str(q2(wages_eur)),
            "expenses_eur": str(q2(expenses_total)),
            "loans_eur": str(q2(loans_total)),
            "taxes_eur": str(q2(taxes_total)),
            "adhoc_eur": str(q2(adhoc_total)),
            "grand_total_eur": str(q2(grand_total)),
        },
    }


def build_finance_inflow_detail(month: str) -> list:
    """
    ExpectedReceipt installments due in the given month (YYYY-MM).
    Only non-cancelled receipts with non-cancelled installments.
    """
    try:
        year, mon = map(int, month.split("-"))
    except (ValueError, AttributeError):
        return []

    from .models import ExpectedReceiptInstallment

    fb = get_fallback_rates()

    installments = (
        ExpectedReceiptInstallment.objects
        .filter(due_date__year=year, due_date__month=mon)
        .select_related("receipt", "receipt__job_order")
        .exclude(receipt__status="cancelled")
        .order_by("due_date", "receipt__customer_name")
    )

    rows = []
    for inst in installments:
        receipt = inst.receipt
        amt_eur = to_eur(inst.amount, inst.currency, {}, fb) or Decimal("0")
        rows.append({
            "installment_id": inst.id,
            "receipt_id": receipt.id,
            "title": receipt.title,
            "reference_no": receipt.reference_no or None,
            "customer_name": receipt.customer_name,
            "job_no": receipt.job_order_id,
            "job_title": receipt.job_order.title if receipt.job_order else None,
            "label": inst.label or f"Taksit {inst.sequence}",
            "sequence": inst.sequence,
            "amount": str(q2(inst.amount)),
            "currency": inst.currency,
            "amount_eur": str(q2(amt_eur)),
            "due_date": inst.due_date.isoformat() if inst.due_date else None,
            "is_received": inst.is_received,
            "received_at": inst.received_at.date().isoformat() if inst.received_at else None,
        })
    return rows


def build_finance_monthly_summary(months_ahead: int = 12) -> list:
    """
    Pre-computed finance outflow totals for each month from the earliest
    loan/expense/tax/adhoc record up to months_ahead from today.
    Used by the cash flow table to avoid per-month fetches.
    """
    from django.utils import timezone
    from dateutil.relativedelta import relativedelta
    from .models import MonthlyExpense, LoanInstallment, TaxEntry, AdHocJobCost, ExpectedReceiptInstallment

    fb = get_fallback_rates()
    today = timezone.now().date()

    # Determine date range: earliest data or today, up to months_ahead
    def earliest_month():
        candidates = []
        first_exp = MonthlyExpense.objects.filter(status="active").order_by("start_date").values_list("start_date", flat=True).first()
        if first_exp:
            candidates.append(first_exp)
        first_loan = LoanInstallment.objects.order_by("due_date").values_list("due_date", flat=True).first()
        if first_loan:
            candidates.append(first_loan)
        first_tax = TaxEntry.objects.order_by("due_date").values_list("due_date", flat=True).first()
        if first_tax:
            candidates.append(first_tax)
        first_adhoc = AdHocJobCost.objects.order_by("cost_date").values_list("cost_date", flat=True).first()
        if first_adhoc:
            candidates.append(first_adhoc)
        first_receipt = ExpectedReceiptInstallment.objects.exclude(receipt__status="cancelled").order_by("due_date").values_list("due_date", flat=True).first()
        if first_receipt:
            candidates.append(first_receipt)
        return min(candidates) if candidates else today

    start = earliest_month().replace(day=1)
    end = (today + relativedelta(months=months_ahead)).replace(day=1)

    results = []
    cursor = start
    while cursor <= end:
        y, m = cursor.year, cursor.month
        mk = f"{y:04d}-{m:02d}"

        wages = compute_monthly_wage(y, m)
        wages_eur = Decimal(wages["total_eur"])

        # Expenses
        expenses_eur = Decimal("0.00")
        for exp in MonthlyExpense.objects.filter(status="active"):
            if expense_applies_to_month(exp, y, m):
                expenses_eur += to_eur(exp.amount, exp.currency, {}, fb) or Decimal("0")

        # Loans
        loans_eur = sum(
            to_eur(inst.total_payment, inst.loan.currency, {}, fb) or Decimal("0")
            for inst in LoanInstallment.objects.filter(due_date__year=y, due_date__month=m).select_related("loan").exclude(loan__status="cancelled")
        )

        # Taxes
        taxes_eur = sum(
            to_eur(t.amount, t.currency, {}, fb) or Decimal("0")
            for t in TaxEntry.objects.filter(due_date__year=y, due_date__month=m)
        )

        # Ad-hoc
        adhoc_eur = sum(
            to_eur(c.amount, c.currency, {}, fb) or Decimal("0")
            for c in AdHocJobCost.objects.filter(cost_date__year=y, cost_date__month=m)
        )

        # Finance inflow (expected receipts)
        receipts_eur = sum(
            to_eur(inst.amount, inst.currency, {}, fb) or Decimal("0")
            for inst in ExpectedReceiptInstallment.objects.filter(due_date__year=y, due_date__month=m).select_related("receipt").exclude(receipt__status="cancelled")
        )

        outflow_total = wages_eur + expenses_eur + Decimal(str(loans_eur)) + Decimal(str(taxes_eur)) + Decimal(str(adhoc_eur))

        results.append({
            "month": mk,
            "wages_eur": str(q2(wages_eur)),
            "expenses_eur": str(q2(expenses_eur)),
            "loans_eur": str(q2(loans_eur)),
            "taxes_eur": str(q2(taxes_eur)),
            "adhoc_eur": str(q2(adhoc_eur)),
            "total_outflow_eur": str(q2(outflow_total)),
            "receipts_inflow_eur": str(q2(receipts_eur)),
            "employee_count": wages["employee_count"],
        })

        cursor = (cursor + relativedelta(months=1)).replace(day=1)

    return results
