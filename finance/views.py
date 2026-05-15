from __future__ import annotations

from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    AdHocJobCost,
    ExpectedReceipt,
    ExpectedReceiptInstallment,
    Loan,
    LoanInstallment,
    MonthlyExpense,
    TaxEntry,
)
from .serializers import (
    AdHocJobCostSerializer,
    ExpectedReceiptInstallmentSerializer,
    ExpectedReceiptSerializer,
    LoanInstallmentSerializer,
    LoanSerializer,
    MonthlyExpenseSerializer,
    TaxEntrySerializer,
)
from .reports import (
    build_finance_inflow_detail,
    build_finance_monthly_summary,
    build_finance_outflow_detail,
)


class MonthlyExpenseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = MonthlyExpenseSerializer

    def get_queryset(self):
        qs = MonthlyExpense.objects.select_related("created_by").order_by("-created_at")
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        return qs

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        expense = self.get_object()
        if expense.status == "cancelled":
            return Response({"detail": "Already cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        expense.status = "cancelled"
        expense.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(expense).data)


class LoanViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LoanSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Loan.objects.select_related("created_by").prefetch_related("installments").order_by("-created_at")
        loan_status = self.request.query_params.get("status")
        if loan_status:
            qs = qs.filter(status=loan_status)
        return qs

    @action(detail=True, methods=["get"], url_path="installments")
    def installments(self, request, pk=None):
        loan = self.get_object()
        qs = loan.installments.all().order_by("sequence")
        serializer = LoanInstallmentSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="installments/(?P<inst_pk>[^/.]+)/mark-paid")
    def mark_installment_paid(self, request, pk=None, inst_pk=None):
        loan = self.get_object()
        try:
            inst = loan.installments.get(pk=inst_pk)
        except LoanInstallment.DoesNotExist:
            return Response({"detail": "Installment not found."}, status=status.HTTP_404_NOT_FOUND)
        if inst.is_paid:
            return Response({"detail": "Already marked as paid."}, status=status.HTTP_400_BAD_REQUEST)
        inst.is_paid = True
        inst.paid_at = timezone.now()
        inst.paid_by = request.user
        inst.save(update_fields=["is_paid", "paid_at", "paid_by"])
        return Response(LoanInstallmentSerializer(inst).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        loan = self.get_object()
        if loan.status == "cancelled":
            return Response({"detail": "Already cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        loan.status = "cancelled"
        loan.save(update_fields=["status"])
        return Response(self.get_serializer(loan).data)


class TaxEntryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = TaxEntrySerializer

    def get_queryset(self):
        qs = TaxEntry.objects.select_related("created_by", "paid_by").order_by("due_date")
        tax_type = self.request.query_params.get("tax_type")
        if tax_type:
            qs = qs.filter(tax_type=tax_type)
        is_paid = self.request.query_params.get("is_paid")
        if is_paid is not None:
            qs = qs.filter(is_paid=is_paid.lower() in ("true", "1", "yes"))
        year = self.request.query_params.get("year")
        if year:
            qs = qs.filter(due_date__year=year)
        return qs

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        entry = self.get_object()
        if entry.is_paid:
            return Response({"detail": "Already marked as paid."}, status=status.HTTP_400_BAD_REQUEST)
        entry.is_paid = True
        entry.paid_at = timezone.now()
        entry.paid_by = request.user
        entry.save(update_fields=["is_paid", "paid_at", "paid_by"])
        return Response(self.get_serializer(entry).data)


class ExpectedReceiptViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ExpectedReceiptSerializer

    def get_queryset(self):
        qs = (
            ExpectedReceipt.objects
            .select_related("created_by", "job_order")
            .prefetch_related("installments__received_by")
            .order_by("-created_at")
        )
        receipt_status = self.request.query_params.get("status")
        if receipt_status:
            qs = qs.filter(status=receipt_status)
        job_order = self.request.query_params.get("job_order")
        if job_order:
            qs = qs.filter(job_order_id=job_order)
        return qs

    @action(detail=True, methods=["get", "post"], url_path="installments")
    def installments(self, request, pk=None):
        receipt = self.get_object()
        if request.method == "POST":
            serializer = ExpectedReceiptInstallmentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(receipt=receipt, currency=receipt.currency)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        qs = receipt.installments.all().order_by("sequence")
        return Response(ExpectedReceiptInstallmentSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="installments/(?P<inst_pk>[^/.]+)/mark-received")
    def mark_installment_received(self, request, pk=None, inst_pk=None):
        receipt = self.get_object()
        try:
            inst = receipt.installments.get(pk=inst_pk)
        except ExpectedReceiptInstallment.DoesNotExist:
            return Response({"detail": "Installment not found."}, status=status.HTTP_404_NOT_FOUND)
        if inst.is_received:
            return Response({"detail": "Already marked as received."}, status=status.HTTP_400_BAD_REQUEST)
        inst.is_received = True
        inst.received_at = timezone.now()
        inst.received_by = request.user
        inst.save(update_fields=["is_received", "received_at", "received_by"])
        return Response(ExpectedReceiptInstallmentSerializer(inst).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        receipt = self.get_object()
        if receipt.status == "cancelled":
            return Response({"detail": "Already cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        receipt.status = "cancelled"
        receipt.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(receipt).data)


class AdHocJobCostViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AdHocJobCostSerializer

    def get_queryset(self):
        qs = (
            AdHocJobCost.objects
            .select_related("created_by", "job_order")
            .order_by("-cost_date")
        )
        job_order = self.request.query_params.get("job_order")
        if job_order:
            qs = qs.filter(job_order_id=job_order)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        year = self.request.query_params.get("year")
        month = self.request.query_params.get("month_num")
        if year:
            qs = qs.filter(cost_date__year=year)
        if month:
            qs = qs.filter(cost_date__month=month)
        return qs


class FinanceReportViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="outflow-detail")
    def outflow_detail(self, request):
        month = request.query_params.get("month", "")
        if not month:
            return Response({"detail": "month parameter required (YYYY-MM)."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(build_finance_outflow_detail(month))

    @action(detail=False, methods=["get"], url_path="inflow-detail")
    def inflow_detail(self, request):
        month = request.query_params.get("month", "")
        if not month:
            return Response({"detail": "month parameter required (YYYY-MM)."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(build_finance_inflow_detail(month))

    @action(detail=False, methods=["get"], url_path="monthly-summary")
    def monthly_summary(self, request):
        try:
            months_ahead = int(request.query_params.get("months_ahead", 12))
        except (ValueError, TypeError):
            months_ahead = 12
        return Response(build_finance_monthly_summary(months_ahead))
