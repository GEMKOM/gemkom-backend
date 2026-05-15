from __future__ import annotations
from decimal import Decimal
from rest_framework import serializers
from django.utils import timezone

from .models import (
    AdHocJobCost,
    ExpectedReceipt,
    ExpectedReceiptInstallment,
    Loan,
    LoanInstallment,
    MonthlyExpense,
    TaxEntry,
)


class MonthlyExpenseSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = MonthlyExpense
        fields = [
            "id", "category", "description", "amount", "currency",
            "recurrence", "start_date", "end_date", "status", "notes",
            "created_by", "created_by_username", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


# ---------------------------------------------------------------------------

class LoanInstallmentSerializer(serializers.ModelSerializer):
    paid_by_username = serializers.CharField(source="paid_by.username", read_only=True)

    class Meta:
        model = LoanInstallment
        fields = [
            "id", "loan", "sequence", "due_date",
            "principal_component", "interest_component", "total_payment",
            "is_paid", "paid_at", "paid_by", "paid_by_username",
        ]
        read_only_fields = [
            "loan", "sequence", "due_date",
            "principal_component", "interest_component", "total_payment",
            "paid_at", "paid_by",
        ]


class LoanSerializer(serializers.ModelSerializer):
    installments = LoanInstallmentSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = Loan
        fields = [
            "id", "name", "principal", "interest_rate", "term_months",
            "currency", "first_payment_date", "status", "notes",
            "created_by", "created_by_username", "created_at",
            "installments",
        ]
        read_only_fields = ["created_by", "created_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        loan = super().create(validated_data)
        loan.generate_installments()
        return loan


# ---------------------------------------------------------------------------

class TaxEntrySerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    paid_by_username = serializers.CharField(source="paid_by.username", read_only=True)

    class Meta:
        model = TaxEntry
        fields = [
            "id", "tax_type", "period_label", "description",
            "amount", "currency", "due_date",
            "is_paid", "paid_at", "paid_by", "paid_by_username",
            "notes", "created_by", "created_by_username", "created_at",
        ]
        read_only_fields = ["paid_at", "paid_by", "created_by", "created_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


# ---------------------------------------------------------------------------

class ExpectedReceiptInstallmentSerializer(serializers.ModelSerializer):
    received_by_username = serializers.CharField(source="received_by.username", read_only=True)

    class Meta:
        model = ExpectedReceiptInstallment
        fields = [
            "id", "receipt", "sequence", "label",
            "amount", "currency", "due_date",
            "is_received", "received_at", "received_by", "received_by_username",
            "notes",
        ]
        read_only_fields = ["receipt", "received_at", "received_by"]


class ExpectedReceiptSerializer(serializers.ModelSerializer):
    installments = ExpectedReceiptInstallmentSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    job_no = serializers.CharField(source="job_order.job_no", read_only=True)

    class Meta:
        model = ExpectedReceipt
        fields = [
            "id", "title", "description", "reference_no", "customer_name",
            "job_order", "job_no", "total_amount", "currency", "status", "notes",
            "created_by", "created_by_username", "created_at", "updated_at",
            "installments",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


# ---------------------------------------------------------------------------

class AdHocJobCostSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    job_no = serializers.CharField(source="job_order.job_no", read_only=True)

    class Meta:
        model = AdHocJobCost
        fields = [
            "id", "job_order", "job_no", "description",
            "amount", "currency", "cost_date", "category", "notes",
            "created_by", "created_by_username", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)
