from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

# Create your models here.
class Machine(models.Model):
    MACHINE_TYPES = [
        ('FTB', 'Zemin Tipi Manuel Borwerk'),
        ('TTB', 'Tabla Tipi Manuel Borwerk'),
        ('HM', 'Yatay İşleme Merkezi'),
        ('HT', 'Yatay Tornalama Merkezi'),
        ('VM', 'Dik İşleme Merkezi'),
        ('DM', 'Matkap'),
        ('SM', 'Kama Kanalı Açma Tezgahı'),
        ('BT', 'Köprü Tipi İşleme Merkezi'),
        ('ACT', 'AJAN Sac Kesim Tezgahı'),
        ('ECT', 'ESAB Sac Kesim Tezgahı'),
        ('CTEDO', 'Dolap Tipi Elektrot Kurutma Fırını'),
        ('OC', 'Tavan Vinci'),
        ('WD', 'Kaynak Makinesi'),
        ('3PB', 'Üç Silindirli Sac Büküm Makinesi'),
        ('LAPTOP', 'Dizüstü Bilgisayar'),
    ]
    USED_IN_CHOICES = [
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
        ('it', 'Bilgi İşlem'),
        ('sales', 'Proje Taahhüt'),
        ('accounting', 'Muhasebe'),
    ]

    name = models.CharField(max_length=255)
    # Optional, searchable asset code; unique when present, multiple NULLs allowed (PostgreSQL)
    code = models.CharField(max_length=255, null=True, blank=True, db_index=True, unique=True)
    # Multi-assign: who is responsible / primary users
    assigned_users = models.ManyToManyField(User, blank=True, related_name="assigned_machines")

    machine_type = models.CharField(max_length=10, choices=MACHINE_TYPES)
    used_in = models.CharField(max_length=50, choices=USED_IN_CHOICES)
    jira_id = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    properties = models.JSONField(default=dict)

    def __str__(self):
        return self.name

    @property
    def is_available(self):
        # Keep your existing relation name if different
        return not self.faults.filter(is_resolved=False).exists()
    
class MachineFault(models.Model):
    machine = models.ForeignKey(
        'Machine', on_delete=models.SET_NULL, null=True, blank=True, related_name='faults'
    )

    # Fallback when machine is unknown/not registered
    asset_name = models.CharField(max_length=200, blank=True, default="")
    location = models.CharField(max_length=150, blank=True, default="")

    reported_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='faults_reported'
    )
    description = models.TextField()

    reported_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='faults_resolved'
    )

    # who is currently responsible
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='faults_assigned'
    )

    # your simple state flags
    is_breaking = models.BooleanField(default=False)
    is_maintenance = models.BooleanField(default=False)

    resolution_description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ['-reported_at']
        indexes = [
            models.Index(fields=['machine']),
            models.Index(fields=['resolved_at']),
            models.Index(fields=['is_breaking']),
            models.Index(fields=['is_maintenance']),
        ]

    @property
    def is_resolved(self) -> bool:
        return bool(self.resolved_at)

    def clean(self):
        # Require at least *something* that identifies the asset when machine is empty
        if not self.machine and not self.asset_name.strip():
            raise ValidationError("Provide 'asset_name' when 'machine' is not selected.")

        # Integrity: resolved_at and resolved_by should come together
        if (self.resolved_at and not self.resolved_by) or (self.resolved_by and not self.resolved_at):
            raise ValidationError("Set both 'resolved_at' and 'resolved_by' (or neither).")

    def save(self, *args, **kwargs):
        # Auto-stamp resolved_at if resolved_by is set and resolved_at missing
        if self.resolved_by and not self.resolved_at:
            self.resolved_at = timezone.now()
        # Clear both if someone tries to unset resolution partially
        if not self.resolved_by and self.resolved_at and not kwargs.get('force_partial_resolution', False):
            # keep atomic: if UI clears resolved_by, also clear resolved_at
            self.resolved_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        label = self.machine.name if self.machine else (self.asset_name or "Unassigned")
        return f"{label} - {'Resolved' if self.resolved_at else 'Unresolved'}"
    
class MachineCalendar(models.Model):
    machine_fk = models.OneToOneField('Machine', on_delete=models.CASCADE, related_name='calendar')
    timezone = models.CharField(max_length=64, default='Europe/Istanbul')

    # Week template: keys "0".."6" (Mon..Sun), each a list of shift dicts:
    # {"start":"07:30","end":"12:30"}, {"start":"13:00","end":"17:00"}
    # Overnight shift example: {"start":"22:00","end":"02:00","end_next_day": true}
    week_template = models.JSONField(default=dict, blank=True)
    work_exceptions = models.JSONField(default=list, blank=True)

    # (Optional) blackout/exception days can be added later with another model.

    def __str__(self):
        return f'Calendar for {self.machine_fk} ({self.timezone})'