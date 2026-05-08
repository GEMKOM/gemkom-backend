from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models, transaction

from approvals.models import ApprovalWorkflow

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Leave type constants — mirrors attendance.AttendanceRecord.LEAVE_TYPE_CHOICES
# ---------------------------------------------------------------------------
LEAVE_ANNUAL       = 'annual_leave'
LEAVE_SICK         = 'sick_leave'
LEAVE_MATERNITY    = 'maternity_leave'
LEAVE_PATERNITY    = 'paternity_leave'
LEAVE_BEREAVEMENT  = 'bereavement_leave'
LEAVE_MARRIAGE     = 'marriage_leave'
LEAVE_PUBLIC_DUTY  = 'public_duty'
LEAVE_COMPENSATORY = 'compensatory_leave'
LEAVE_UNPAID       = 'unpaid_leave'
LEAVE_BUSINESS_TRIP = 'business_trip'
LEAVE_HALF_DAY     = 'half_day'
LEAVE_PAID         = 'paid_leave'

LEAVE_TYPE_CHOICES = [
    (LEAVE_ANNUAL,        'Yıllık İzin'),
    (LEAVE_SICK,          'Hastalık İzni'),
    (LEAVE_MATERNITY,     'Doğum İzni'),
    (LEAVE_PATERNITY,     'Babalık İzni'),
    (LEAVE_BEREAVEMENT,   'Ölüm İzni'),
    (LEAVE_MARRIAGE,      'Evlilik İzni'),
    (LEAVE_PUBLIC_DUTY,   'Resmi Görev'),
    (LEAVE_COMPENSATORY,  'Mazeret İzni'),
    (LEAVE_BUSINESS_TRIP, 'Görev Seyahati'),
    (LEAVE_HALF_DAY,      'Yarım Gün'),
    (LEAVE_PAID,          'Ücretli İzin'),
    (LEAVE_UNPAID,        'Ücretsiz İzin'),
]


def _working_days_in_range(start: date, end: date) -> tuple[int, set[date]]:
    """
    Returns (count_of_working_days, set_of_excluded_dates).
    Excludes weekends and public holidays.
    """
    from attendance.models import PublicHoliday

    holidays: set[date] = set(
        PublicHoliday.objects.filter(date__gte=start, date__lte=end)
        .values_list("date", flat=True)
    )
    excluded: set[date] = set()
    count = 0
    current = start
    while current <= end:
        if current.weekday() >= 5 or current in holidays:
            excluded.add(current)
        else:
            count += 1
        current += timedelta(days=1)
    return count, excluded


class VacationRequest(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_APPROVED  = "approved"
    STATUS_REJECTED  = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_SUBMITTED, "Onay Bekliyor"),
        (STATUS_APPROVED,  "Onaylandı"),
        (STATUS_REJECTED,  "Reddedildi"),
        (STATUS_CANCELLED, "İptal Edildi"),
    ]

    requester    = models.ForeignKey(User, on_delete=models.PROTECT, related_name="vacation_requests")
    team         = models.CharField(max_length=50, blank=True)  # snapshot at submission
    leave_type   = models.CharField(max_length=30, choices=LEAVE_TYPE_CHOICES, default=LEAVE_ANNUAL)
    start_date   = models.DateField()
    end_date     = models.DateField()
    duration_days = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    reason       = models.TextField(blank=True)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)

    approvals = GenericRelation(ApprovalWorkflow, related_query_name="vacation_request")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["start_date"]),
            models.Index(fields=["end_date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["requester"]),
        ]

    def __str__(self):
        return f"VR #{self.pk} | {self.requester_id} | {self.start_date}→{self.end_date} | {self.status}"

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("end_date must be on or after start_date.")

    def compute_duration_days(self) -> Decimal:
        if not (self.start_date and self.end_date):
            return Decimal("0")
        count, _ = _working_days_in_range(self.start_date, self.end_date)
        return Decimal(str(count))

    def save(self, *args, **kwargs):
        if self.start_date and self.end_date:
            self.duration_days = self.compute_duration_days()
        super().save(*args, **kwargs)

    # ===== Approval wiring =====

    def _snapshot_for_workflow(self) -> dict:
        return {
            "vacation_request": {
                "id": self.pk,
                "requester_id": self.requester_id,
                "team": self.team,
                "leave_type": self.leave_type,
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "duration_days": str(self.duration_days),
                "reason": self.reason,
            }
        }

    @transaction.atomic
    def send_for_approval(self):
        from vacation_requests.approval_service import submit_vacation_request
        return submit_vacation_request(self, by_user=self.requester)

    def handle_approval_event(self, *, workflow: ApprovalWorkflow, event: str, payload: dict | None = None):
        if event == "approved":
            if self.status != "approved":
                self.status = "approved"
                self.save(update_fields=["status", "updated_at"])
            self._create_attendance_records()
            self._deduct_leave_balance()
        elif event == "rejected":
            if self.status != "rejected":
                self.status = "rejected"
                self.save(update_fields=["status", "updated_at"])
        elif event == "cancelled":
            if self.status != "cancelled":
                self.status = "cancelled"
                self.save(update_fields=["status", "updated_at"])
            self._rollback_attendance_records()
            self._refund_leave_balance()

    # ===== Attendance auto-creation =====

    def _attendance_note_tag(self) -> str:
        return f"vr:{self.pk}"

    def _create_attendance_records(self):
        from attendance.models import AttendanceRecord

        _, excluded = _working_days_in_range(self.start_date, self.end_date)
        tag = self._attendance_note_tag()
        current = self.start_date
        while current <= self.end_date:
            if current not in excluded:
                AttendanceRecord.objects.get_or_create(
                    user_id=self.requester_id,
                    date=current,
                    defaults={
                        "status": AttendanceRecord.STATUS_LEAVE,
                        "leave_type": self.leave_type,
                        "method": AttendanceRecord.METHOD_HR,
                        "notes": tag,
                    },
                )
            current += timedelta(days=1)

    def _rollback_attendance_records(self):
        from attendance.models import AttendanceRecord

        tag = self._attendance_note_tag()
        AttendanceRecord.objects.filter(
            user_id=self.requester_id,
            notes=tag,
            status=AttendanceRecord.STATUS_LEAVE,
        ).delete()

    # ===== Leave balance =====

    def _deduct_leave_balance(self):
        if not self.start_date:
            return
        balance, _ = UserLeaveBalance.objects.get_or_create(
            user_id=self.requester_id,
            year=self.start_date.year,
            leave_type=self.leave_type,
            defaults={"total_days": Decimal("0"), "used_days": Decimal("0")},
        )
        balance.used_days += self.duration_days
        balance.save(update_fields=["used_days"])

    def _refund_leave_balance(self):
        if not self.start_date:
            return
        try:
            balance = UserLeaveBalance.objects.get(
                user_id=self.requester_id,
                year=self.start_date.year,
                leave_type=self.leave_type,
            )
        except UserLeaveBalance.DoesNotExist:
            return
        balance.used_days = max(Decimal("0"), balance.used_days - self.duration_days)
        balance.save(update_fields=["used_days"])


class UserLeaveBalance(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="leave_balances")
    year       = models.PositiveIntegerField()
    leave_type = models.CharField(max_length=30, choices=LEAVE_TYPE_CHOICES)
    total_days = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    used_days  = models.DecimalField(max_digits=6, decimal_places=1, default=0)

    class Meta:
        unique_together = [("user", "year", "leave_type")]
        ordering = ["user", "year", "leave_type"]

    def __str__(self):
        return f"{self.user_id} | {self.year} | {self.leave_type} | {self.used_days}/{self.total_days}"

    @property
    def remaining_days(self) -> Decimal:
        return max(Decimal("0"), self.total_days - self.used_days)
