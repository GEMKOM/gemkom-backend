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


class AttendanceRecord(models.Model):
    METHOD_IP = 'ip'
    METHOD_GPS = 'gps'
    METHOD_OVERRIDE = 'manual_override'
    METHOD_HR = 'hr_manual'

    METHOD_CHOICES = [
        (METHOD_IP, 'IP (Ofis Ağı)'),
        (METHOD_GPS, 'GPS'),
        (METHOD_OVERRIDE, 'Manuel Değişim Talebi'),
        (METHOD_HR, 'Manuel'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_COMPLETE = 'complete'
    STATUS_PENDING = 'pending_override'
    STATUS_PENDING_CHECKOUT = 'pending_checkout_override'
    STATUS_REJECTED = 'override_rejected'

    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Aktif (Giriş Yapıldı)'),
        (STATUS_COMPLETE, 'Tamamlandı (Çıkış Yapıldı)'),
        (STATUS_PENDING, 'İnsan Kaynakları Onayı Bekliyor (GİRİŞ)'),
        (STATUS_PENDING_CHECKOUT, 'İnsan Kaynakları Onayı Bekliyor (ÇIKIŞ)'),
        (STATUS_REJECTED, 'Reddedildi'),
    ]

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='attendance_records')
    date = models.DateField(db_index=True)

    check_in_time = models.DateTimeField()
    check_out_time = models.DateTimeField(null=True, blank=True)

    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    # Audit coordinates (for future GPS support — stored but not enforced for IP check-ins)
    check_in_lat = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    check_in_lon = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    check_out_lat = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    check_out_lon = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)

    client_ip = models.GenericIPAddressField(null=True, blank=True)

    # Override fields — used for both check-in and checkout override reasons
    override_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_attendance_overrides',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

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

    def __str__(self):
        return f"{self.user} | {self.date} | {self.status}"
