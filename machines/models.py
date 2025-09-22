from django.db import models
from django.contrib.auth.models import User

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
    machine = models.ForeignKey('Machine', on_delete=models.CASCADE, related_name='faults')
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='faults_reported')
    description = models.TextField()
    reported_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='faults_resolved')
    is_breaking = models.BooleanField(default=False)
    is_maintenance = models.BooleanField(default=False)
    resolution_description = models.TextField(default="")

    class Meta:
        ordering = ['-reported_at']

    def __str__(self):
        return f"{self.machine.name} - {'Resolved' if self.resolved_at else 'Unresolved'}"
    
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