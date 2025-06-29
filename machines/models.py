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
    ]

    name = models.CharField(max_length=255)
    machine_type = models.CharField(max_length=10, choices=MACHINE_TYPES)
    used_in = models.CharField(max_length=50)
    jira_id = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(null=True, blank=True, default=True)
    properties = models.JSONField(default=dict)  # Store dynamic properties here

    def __str__(self):
        return self.name
    
    @property
    def is_available(self):
        return not self.faults.filter(is_resolved=False).exists()
    
class MachineFault(models.Model):
    machine = models.ForeignKey('Machine', on_delete=models.CASCADE, related_name='faults')
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    description = models.TextField()
    reported_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-reported_at']

    def __str__(self):
        return f"{self.machine.name} - {'Resolved' if self.is_resolved else 'Unresolved'}"
    