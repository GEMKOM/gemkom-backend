from django.db import models
from django.contrib.auth.models import User
from django.contrib.auth import get_user_model
User = get_user_model()

class UserProfile(models.Model):
    TEAM_CHOICES = [
        ('machining', 'Talaşlı İmalat'),
        ('design', 'Dizayn'),
        ('logistics', 'Lojistik'),
        ('procurement', 'Satın Alma'),
        ('welding', 'Kaynaklı İmalat'),
        ('planning', 'Planlama'),
        ('manufacturing', 'İmalat'),
        ('maintenance', "Bakım"),
        ('rollingmill', 'Haddehane'),
        ('qualitycontrol', 'Kalite Kontrol'),
        ('cutting', 'CNC Kesim'),
        ('warehouse', 'Ambar'),
        ('finance', 'Finans'),
        ('management', 'Yönetim'),
        ('external_workshops', 'Dış Atölyeler'),
        ('human_resouces', 'İnsan Kaynakları'),
        ('sales', 'Proje Taahhüt'),
        ('accounting', 'Muhasebe'),
        # Add more as needed
    ]
    OCCUPATION_CHOICES = [
        ('manager', 'Müdür'),
        ('welder', 'Kaynakçı'),
        ('foreman', 'Formen'),
        ('assembler', 'Montajcı'),
        ('helper', 'Yardımcı'),
        ('operator', 'Operatör'),
        ('office', 'Ofis çalışanı')
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    team = models.CharField(max_length=50, choices=TEAM_CHOICES, null=True, blank=True)
    must_reset_password = models.BooleanField(default=False)
    reset_password_request = models.BooleanField(default=False)
    jira_api_token = models.CharField(max_length=255, blank=True, null=True)
    occupation = models.CharField(max_length=50, choices=OCCUPATION_CHOICES, null=True, blank=True)
    location_type = [
        ('workshop', 'Atölye'),
        ('office', 'Ofis'),
    ]
    work_location = models.CharField(max_length=10, choices=location_type, default='workshop')

    class Meta:
        default_permissions = ()  # suppress add/change/delete/view_userprofile

    def __str__(self):
        return self.user.username

class WageRate(models.Model):
    """
    Versioned wage records per user.
    Keep history by effective_from. The 'current' wage is the one with the
    latest effective_from not in the future.
    """
    CURRENCY_CHOICES = [
        ("TRY", "TRY"),
        ("USD", "USD"),
        ("EUR", "EUR"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="wage_rates")
    effective_from = models.DateField(db_index=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="TRY")

    # Base hourly rate for weekday work window (Mon–Fri 07:30–17:00, Europe/Istanbul)
    base_monthly = models.DecimalField(max_digits=12, decimal_places=4)

    # Multipliers for your three pay buckets; keep simple now, flexible later
    after_hours_multiplier = models.DecimalField(max_digits=6, decimal_places=3, default=1.5)
    sunday_multiplier      = models.DecimalField(max_digits=6, decimal_places=3, default=2.0)

    note = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        # Optional: fine-grained, app-level perms you can grant only to HR/authorized managers
        permissions = [
            ("view_wage",   "Can view wages"),
            ("add_wage",    "Can add wages"),
            ("change_wage", "Can change wages"),
            ("delete_wage", "Can delete wages"),
        ]
        indexes = [
            models.Index(fields=["user", "effective_from"]),
        ]
        constraints = [
            # Prevent two wage rows with the same effective_from for one user
            models.UniqueConstraint(fields=["user", "effective_from"], name="uniq_user_wage_effective_from"),
        ]

    def __str__(self):
        return f"{self.user.username} @ {self.effective_from} {self.base_monthly} {self.currency}"


class UserPermissionOverride(models.Model):
    """
    Explicit per-user permission grants or denies.

    Overrides take priority over group membership in user_has_role_perm():
      - granted=True  → user has this permission regardless of groups
      - granted=False → user is explicitly denied this permission regardless of groups

    Use sparingly. Prefer assigning users to additional groups instead.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='permission_overrides',
    )
    codename = models.CharField(max_length=100)
    granted = models.BooleanField(
        default=True,
        help_text='True = explicit grant, False = explicit deny',
    )
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'codename')]
        ordering = ['user', 'codename']

    def __str__(self):
        action = 'GRANT' if self.granted else 'DENY'
        return f'{action} {self.codename} → {self.user_id}'