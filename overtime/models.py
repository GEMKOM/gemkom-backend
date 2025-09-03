# overtime/models.py
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType

# approvals imports
from approvals.models import (
    ApprovalWorkflow,
    ApprovalStage,
    ApprovalStageInstance,
    ApprovalPolicy,
)

User = settings.AUTH_USER_MODEL


class OvertimeRequest(models.Model):
    STATUS_CHOICES = [
        ("submitted", "Onay Bekliyor"),
        ("approved", "Onaylandı"),
        ("rejected", "Reddedildi"),
        ("cancelled", "İptal Edildi"),
    ]

    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="overtime_requests")
    team = models.CharField(max_length=50, blank=True)  # snapshot of requester.profile.team
    reason = models.TextField(blank=True)

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="submitted")
    duration_hours = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    # Link to approvals
    approvals = GenericRelation(ApprovalWorkflow, related_query_name="overtime_request")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["start_at"]),
            models.Index(fields=["end_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["requester"]),
            models.Index(fields=["team"]),
        ]

    def __str__(self):
        return f"OT #{self.pk} | {self.start_at} → {self.end_at} | {self.status}"

    def clean(self):
        if self.end_at <= self.start_at:
            raise ValidationError("end_at must be after start_at.")

    def compute_duration_hours(self):
        delta = self.end_at - self.start_at
        return round(delta.total_seconds() / 3600, 2)

    def save(self, *args, **kwargs):
        self.duration_hours = self.compute_duration_hours()
        super().save(*args, **kwargs)

    # ===== Approval wiring =====

    def _select_policy(self) -> ApprovalPolicy | None:
        """
        Choose an ApprovalPolicy for this overtime request.
        Adjust rules as you like. Example rules:
        - Use is_rolling_mill when team == 'rollingmill'
        - Only active policies
        - Lowest selection_priority wins
        """
        qs = ApprovalPolicy.objects.filter(is_active=True)

        # Example mapping for your earlier pattern (you used is_rolling_mill in PR approvals):
        if (self.team or "").lower() in {"rollingmill", "haddehane"}:
            qs = qs.filter(is_rolling_mill=True)
        else:
            qs = qs.filter(is_rolling_mill=False)

        # If you want to drive by "priority_in", you can store "overtime" or team names there
        # and add an extra filter like:
        # qs = qs.filter(Q(priority_in__len=0) | Q(priority_in__contains=["overtime"]))

        return qs.order_by("selection_priority").first()

    def _snapshot_for_workflow(self) -> dict:
        """
        Persist enough data so approvers see context even if things change later.
        """
        return {
            "overtime": {
                "id": self.pk,
                "requester_id": self.requester_id,
                "team": self.team,
                "reason": self.reason,
                "start_at": self.start_at.isoformat(),
                "end_at": self.end_at.isoformat(),
                "duration_hours": str(self.duration_hours),
                "entries": [
                    {
                        "id": e.id,
                        "user_id": e.user_id,
                        "job_no": e.job_no,
                        "description": e.description,
                    }
                    for e in self.entries.all()
                ],
            }
        }

    @transaction.atomic
    def send_for_approval(self):
        from overtime.approval_service import submit_overtime_request
        return submit_overtime_request(self, by_user=self.requester)

    # This is the callback the approvals system should call when state changes
    def handle_approval_event(self, *, workflow: ApprovalWorkflow, event: str, payload: dict | None = None):
        """
        Contract for approvals app:
          subject.handle_approval_event(workflow=..., event='approved'/'rejected'/'stage_advanced'/'cancelled', payload={...})

        On final approval -> mark OT 'approved'
        On rejection     -> mark OT 'rejected'
        On cancellation  -> mark OT 'cancelled'
        On stage advance -> no status change
        """
        if event == "approved":
            if self.status != "approved":
                self.status = "approved"
                self.save(update_fields=["status", "updated_at"])
        elif event == "rejected":
            if self.status != "rejected":
                self.status = "rejected"
                self.save(update_fields=["status", "updated_at"])
        elif event == "cancelled":
            if self.status != "cancelled":
                self.status = "cancelled"
                self.save(update_fields=["status", "updated_at"])
        elif event == "stage_advanced":
            # you may want to notify requester; leave DB unchanged
            pass
        else:
            # unknown event – no-op
            pass


class OvertimeEntry(models.Model):
    request = models.ForeignKey(OvertimeRequest, on_delete=models.CASCADE, related_name="entries")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="overtime_entries")
    job_no = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    approved_hours = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["request", "user"]),
        ]

    def __str__(self):
        return f"OT Entry #{self.pk} | {self.user} | {self.job_no}"
