from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class AttendanceSite(models.Model):
    """
    Singleton-style config for the company premises.
    HR manages this from the admin panel.
    """
    name = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=12, decimal_places=6)
    longitude = models.DecimalField(max_digits=12, decimal_places=6)
    radius_meters = models.PositiveIntegerField(
        default=150,
        help_text="GPS geofence radius in metres (for future blue-collar use).",
    )
    allowed_ip_ranges = models.JSONField(
        default=list,
        help_text='List of CIDR strings for office IP ranges, e.g. ["192.168.1.0/24", "10.0.0.5/32"].',
    )

    class Meta:
        verbose_name = "Attendance Site"
        verbose_name_plural = "Attendance Sites"

    def __str__(self):
        return self.name


class ShiftRule(models.Model):
    """
    Defines expected working hours for overtime calculation.
    One rule can be marked as is_default — used when a user has no explicit assignment.
    """
    name = models.CharField(max_length=100)
    expected_start = models.TimeField(help_text="Shift start time (e.g. 08:00).")
    expected_end = models.TimeField(help_text="Shift end time (e.g. 17:00).")
    overtime_threshold_minutes = models.PositiveIntegerField(
        default=15,
        help_text="How many minutes past expected_end before overtime is flagged.",
    )
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False,
        help_text="Used for users with no explicit shift rule assigned. Only one rule should be default.",
    )

    class Meta:
        verbose_name = "Shift Rule"
        verbose_name_plural = "Shift Rules"
        ordering = ['name']

    def __str__(self):
        default_tag = " [Varsayılan]" if self.is_default else ""
        return f"{self.name}{default_tag}"

    def save(self, *args, **kwargs):
        # Ensure only one rule is default at a time
        if self.is_default:
            ShiftRule.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class PublicHoliday(models.Model):
    """
    Turkish public holidays fetched from Nager.Date API and stored locally.
    Seeded via: python manage.py seed_holidays
    """
    date = models.DateField(unique=True, db_index=True)
    name = models.CharField(max_length=255, help_text="English name")
    local_name = models.CharField(max_length=255, help_text="Turkish name")

    class Meta:
        verbose_name = "Public Holiday"
        verbose_name_plural = "Public Holidays"
        ordering = ['date']

    def __str__(self):
        return f"{self.date} — {self.local_name}"


class AttendanceRecord(models.Model):
    METHOD_IP = 'ip'
    METHOD_GPS = 'gps'
    METHOD_OVERRIDE = 'manual_override'
    METHOD_HR = 'hr_manual'

    METHOD_CHOICES = [
        (METHOD_IP, 'IP (Ofis Ağı)'),
        (METHOD_GPS, 'GPS'),
        (METHOD_OVERRIDE, 'Manuel Değişim Talebi'),
        (METHOD_HR, 'HR Değişikliği'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_COMPLETE = 'complete'
    STATUS_PENDING = 'pending_override'
    STATUS_PENDING_CHECKOUT = 'pending_checkout_override'
    STATUS_REJECTED = 'override_rejected'
    STATUS_LEAVE = 'leave'

    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Aktif (Giriş Yapıldı)'),
        (STATUS_COMPLETE, 'Tamamlandı (Çıkış Yapıldı)'),
        (STATUS_PENDING, 'İnsan Kaynakları Onayı Bekliyor (GİRİŞ)'),
        (STATUS_PENDING_CHECKOUT, 'İnsan Kaynakları Onayı Bekliyor (ÇIKIŞ)'),
        (STATUS_REJECTED, 'Reddedildi'),
        (STATUS_LEAVE, 'İzinli'),
    ]

    # Leave / absence day types — only set when status=leave
    LEAVE_ANNUAL = 'annual_leave'
    LEAVE_SICK = 'sick_leave'
    LEAVE_MATERNITY = 'maternity_leave'
    LEAVE_PATERNITY = 'paternity_leave'
    LEAVE_BEREAVEMENT = 'bereavement_leave'
    LEAVE_MARRIAGE = 'marriage_leave'
    LEAVE_PUBLIC_DUTY = 'public_duty'
    LEAVE_COMPENSATORY = 'compensatory_leave'
    LEAVE_UNPAID = 'unpaid_leave'
    LEAVE_UNAUTHORIZED = 'unauthorized_absence'
    LEAVE_BUSINESS_TRIP = 'business_trip'
    LEAVE_HALF_DAY = 'half_day'
    LEAVE_PAID = 'paid_leave'

    LEAVE_TYPE_CHOICES = [
        # Paid
        (LEAVE_ANNUAL,       'Yıllık İzin'),
        (LEAVE_SICK,         'Hastalık İzni'),
        (LEAVE_MATERNITY,    'Doğum İzni'),
        (LEAVE_PATERNITY,    'Babalık İzni'),
        (LEAVE_BEREAVEMENT,  'Ölüm İzni'),
        (LEAVE_MARRIAGE,     'Evlilik İzni'),
        (LEAVE_PUBLIC_DUTY,  'Resmi Görev'),
        (LEAVE_COMPENSATORY, 'Mazeret İzni'),
        (LEAVE_BUSINESS_TRIP,'Görev Seyahati'),
        (LEAVE_HALF_DAY,     'Yarım Gün'),
        (LEAVE_PAID,         'Ücretli İzin'),
        # Unpaid
        (LEAVE_UNPAID,       'Ücretsiz İzin'),
        (LEAVE_UNAUTHORIZED, 'İzinsiz Devamsızlık'),
    ]

    PAID_LEAVE_TYPES = {
        LEAVE_ANNUAL, LEAVE_SICK, LEAVE_MATERNITY, LEAVE_PATERNITY,
        LEAVE_BEREAVEMENT, LEAVE_MARRIAGE, LEAVE_PUBLIC_DUTY,
        LEAVE_COMPENSATORY, LEAVE_BUSINESS_TRIP, LEAVE_HALF_DAY, LEAVE_PAID,
    }

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='attendance_records')
    date = models.DateField(db_index=True)

    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)

    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    # Audit coordinates (for future GPS support — stored but not enforced for IP check-ins)
    check_in_lat = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    check_in_lon = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    check_out_lat = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    check_out_lon = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)

    client_ip = models.GenericIPAddressField(null=True, blank=True)

    # Leave type — only set when status=leave
    leave_type = models.CharField(
        max_length=30, choices=LEAVE_TYPE_CHOICES,
        null=True, blank=True,
    )

    # Override fields — used for both check-in and checkout override reasons
    override_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_attendance_overrides',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    overtime_minutes = models.IntegerField(default=0)
    # Shift compliance — computed on checkout against the user's ShiftRule
    late_minutes = models.IntegerField(
        default=0,
        help_text="Minutes after expected_start the user checked in. 0 = on time or early.",
    )
    early_leave_minutes = models.IntegerField(
        default=0,
        help_text="Minutes before expected_end the user checked out. 0 = stayed full shift or later.",
    )
    notes = models.TextField(
        blank=True,
        help_text="HR notes. For leave records, use this to record leave context (e.g. approval info, compensatory details).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Attendance Record"
        verbose_name_plural = "Attendance Records"
        ordering = ['-date', '-check_in_time']
        constraints = [
            # One record per user per day (prevents duplicate check-ins)
            models.UniqueConstraint(fields=['user', 'date'], name='uniq_attendance_user_date'),
        ]
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['date']),
            models.Index(fields=['status']),
        ]

    @property
    def is_paid_leave(self):
        return self.leave_type in self.PAID_LEAVE_TYPES

    def __str__(self):
        if self.leave_type:
            return f"{self.user} | {self.date} | {self.get_leave_type_display()}"
        return f"{self.user} | {self.date} | {self.status}"


class AttendanceLeaveInterval(models.Model):
    """
    A partial-day leave window attached to an AttendanceRecord.
    Used when an employee works part of the day but has approved leave for a specific time interval
    (e.g. arrived 90 min late, or left 2h early).
    The parent record retains the actual work session check_in/check_out times.
    """
    record = models.ForeignKey(
        AttendanceRecord,
        on_delete=models.CASCADE,
        related_name='leave_intervals',
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    leave_type = models.CharField(max_length=30, choices=AttendanceRecord.LEAVE_TYPE_CHOICES)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Leave Interval"
        verbose_name_plural = "Leave Intervals"
        ordering = ['start_time']

    def __str__(self):
        return (
            f"{self.record.user} | {self.record.date} | "
            f"{self.get_leave_type_display()} "
            f"{self.start_time:%H:%M}–{self.end_time:%H:%M}"
        )
