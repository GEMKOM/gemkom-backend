from django.db import models
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
    properties = models.JSONField(default=dict)  # Store dynamic properties here

    def __str__(self):
        return self.name