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
LEAVE_ANNUAL        = 'annual_leave'
LEAVE_SICK          = 'sick_leave'
LEAVE_MATERNITY     = 'maternity_leave'
LEAVE_PATERNITY     = 'paternity_leave'
LEAVE_BEREAVEMENT   = 'bereavement_leave'
LEAVE_MARRIAGE      = 'marriage_leave'
LEAVE_PUBLIC_DUTY   = 'public_duty'
LEAVE_COMPENSATORY  = 'compensatory_leave'
LEAVE_UNPAID        = 'unpaid_leave'
LEAVE_BUSINESS_TRIP = 'business_trip'
LEAVE_PAID          = 'paid_leave'

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
    (LEAVE_PAID,          'Ücretli İzin'),
    (LEAVE_UNPAID,        'Ücretsiz İzin'),
]


def _working_days_in_range(start: date, end: date) -> tuple[Decimal, set[date]]:
    """
    Returns (working_day_count, set_of_excluded_dates).
    Excluded dates get no attendance record created (weekends + full public holidays).
    Half-day holidays (Arife) count 0.5 and DO get a leave record so employees
    aren't flagged absent for the morning portion.
    """
    from attendance.models import PublicHoliday

    holiday_rows = PublicHoliday.objects.filter(date__gte=start, date__lte=end).values("date", "is_half_day")
    half_day_holidays: set[date] = set()
    full_holidays: set[date] = set()
    for row in holiday_rows:
        if row["is_half_day"]:
            half_day_holidays.add(row["date"])
        else:
            full_holidays.add(row["date"])

    excluded: set[date] = set()
    count = Decimal("0")
    current = start
    while current <= end:
        if current.weekday() >= 5 or current in full_holidays:
            excluded.add(current)
        elif current in half_day_holidays:
            count += Decimal("0.5")
            # not excluded — leave record IS created so employee isn't flagged absent
        else:
            count += Decimal("1")
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
    # Compensatory leave only — the exact time window on that single day
    start_time   = models.TimeField(null=True, blank=True)
    end_time     = models.TimeField(null=True, blank=True)
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
        if self.leave_type == LEAVE_COMPENSATORY:
            return Decimal("0")  # compensatory is tracked in hours, not days
        count, _ = _working_days_in_range(self.start_date, self.end_date)
        return count

    def save(self, *args, **kwargs):
        if self.start_date and self.end_date:
            self.duration_days = self.compute_duration_days()
        super().save(*args, **kwargs)

    # ===== Approval wiring =====

    def _snapshot_for_workflow(self) -> dict:
        snap = {
            "id": self.pk,
            "requester_id": self.requester_id,
            "team": self.team,
            "leave_type": self.leave_type,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "duration_days": str(self.duration_days),
            "reason": self.reason,
        }
        if self.leave_type == LEAVE_COMPENSATORY:
            snap["start_time"] = self.start_time.isoformat() if self.start_time else None
            snap["end_time"]   = self.end_time.isoformat()   if self.end_time   else None
        return {"vacation_request": snap}

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
        from attendance.models import AttendanceLeaveInterval, AttendanceRecord
        from datetime import datetime

        tag = self._attendance_note_tag()

        if self.leave_type == LEAVE_COMPENSATORY:
            # Compensatory: create/find the day's record then attach a leave interval.
            # Multiple compensatory requests on the same day are each their own interval.
            record, _ = AttendanceRecord.objects.get_or_create(
                user_id=self.requester_id,
                date=self.start_date,
                defaults={
                    "status": AttendanceRecord.STATUS_LEAVE,
                    "leave_type": LEAVE_COMPENSATORY,
                    "method": AttendanceRecord.METHOD_HR,
                    "notes": tag,
                },
            )
            start_dt = datetime.combine(self.start_date, self.start_time)
            end_dt   = datetime.combine(self.start_date, self.end_time)
            AttendanceLeaveInterval.objects.get_or_create(
                record=record,
                start_time=start_dt,
                end_time=end_dt,
                defaults={"leave_type": LEAVE_COMPENSATORY, "notes": tag},
            )
        else:
            _, excluded = _working_days_in_range(self.start_date, self.end_date)
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
        from attendance.models import AttendanceLeaveInterval, AttendanceRecord

        tag = self._attendance_note_tag()

        if self.leave_type == LEAVE_COMPENSATORY:
            # Only delete the specific interval; leave the parent record intact
            # (the employee may have other records or intervals on that day).
            deleted, _ = AttendanceLeaveInterval.objects.filter(notes=tag).delete()
            # If the parent record was created solely by this request (tagged), clean it up.
            AttendanceRecord.objects.filter(
                user_id=self.requester_id,
                date=self.start_date,
                notes=tag,
                status=AttendanceRecord.STATUS_LEAVE,
            ).delete()
        else:
            AttendanceRecord.objects.filter(
                user_id=self.requester_id,
                notes=tag,
                status=AttendanceRecord.STATUS_LEAVE,
            ).delete()

    # ===== Leave balance (annual_leave only) =====

    def _deduct_leave_balance(self):
        if self.leave_type != LEAVE_ANNUAL:
            return
        balance, _ = UserLeaveBalance.objects.get_or_create(
            user_id=self.requester_id,
            defaults={"total_days": Decimal("0"), "used_days": Decimal("0")},
        )
        balance.used_days += self.duration_days
        balance.save(update_fields=["used_days"])
        LeaveBalanceLog.objects.create(
            user_id=self.requester_id,
            kind=LeaveBalanceLog.KIND_REQUEST_DEDUCT,
            delta=-self.duration_days,
            balance_after=balance.remaining_days,
            vacation_request=self,
            note=f"İzin talebi #{self.pk} onaylandı ({self.start_date} → {self.end_date})",
        )

    def _refund_leave_balance(self):
        if self.leave_type != LEAVE_ANNUAL:
            return
        try:
            balance = UserLeaveBalance.objects.get(user_id=self.requester_id)
        except UserLeaveBalance.DoesNotExist:
            return
        balance.used_days = balance.used_days - self.duration_days
        balance.save(update_fields=["used_days"])
        LeaveBalanceLog.objects.create(
            user_id=self.requester_id,
            kind=LeaveBalanceLog.KIND_REQUEST_REFUND,
            delta=self.duration_days,
            balance_after=balance.remaining_days,
            vacation_request=self,
            note=f"İzin talebi #{self.pk} iptal/reddedildi ({self.start_date} → {self.end_date})",
        )


class UserLeaveBalance(models.Model):
    """
    One row per user. Tracks annual leave (yıllık izin) only.
    total_days is set manually by HR — includes carry-over from before the system.
    used_days is managed automatically on approval/cancellation.
    """
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name="leave_balance")
    total_days = models.DecimalField(max_digits=6, decimal_places=1, default=0,
                                     help_text="Total annual leave days available (set by HR, includes carry-over).")
    used_days  = models.DecimalField(max_digits=6, decimal_places=1, default=0,
                                     help_text="Days used (auto-managed by the system).")
    last_credited_date = models.DateField(
        null=True, blank=True,
        help_text="Date of the last anniversary credit. Set by the credit_annual_leave command.",
    )

    class Meta:
        ordering = ["user"]

    def __str__(self):
        return f"{self.user_id} | {self.used_days}/{self.total_days} gün"

    @property
    def remaining_days(self) -> Decimal:
        return self.total_days - self.used_days


class LeaveBalanceLog(models.Model):
    """
    Append-only ledger of every event that changes a user's annual leave balance.
    Each row records the delta and the running balance after the change.
    """
    KIND_HR_ADJUSTMENT  = "hr_adjustment"
    KIND_ANNIVERSARY    = "anniversary_credit"
    KIND_REQUEST_DEDUCT = "request_deduct"
    KIND_REQUEST_REFUND = "request_refund"

    KIND_CHOICES = [
        (KIND_HR_ADJUSTMENT,  "HR Düzeltmesi"),
        (KIND_ANNIVERSARY,    "Yıllık Kredi"),
        (KIND_REQUEST_DEDUCT, "İzin Talebi Kesintisi"),
        (KIND_REQUEST_REFUND, "İzin Talebi İadesi"),
    ]

    user            = models.ForeignKey(User, on_delete=models.CASCADE, related_name="leave_balance_logs")
    kind            = models.CharField(max_length=30, choices=KIND_CHOICES)
    delta           = models.DecimalField(max_digits=6, decimal_places=1,
                                         help_text="Positive = added, negative = deducted.")
    balance_after   = models.DecimalField(max_digits=6, decimal_places=1,
                                         help_text="Remaining days after this entry.")
    # Optional link to the vacation request that caused this entry
    vacation_request = models.ForeignKey(
        "VacationRequest", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="balance_logs",
    )
    note            = models.TextField(blank=True)
    created_by      = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leave_balance_log_actions",
    )
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.user_id} | {self.get_kind_display()} | {sign}{self.delta} → {self.balance_after}"
