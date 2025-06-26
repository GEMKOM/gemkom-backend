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


    machine_type = models.CharField(max_length=50, choices=MACHINE_TYPES)
    is_cnc = models.BooleanField(default=False)
    model_name = models.CharField(max_length=100)

    axis_x = models.IntegerField(help_text="mm")
    axis_y = models.IntegerField(help_text="mm")
    axis_z = models.IntegerField(help_text="mm")
    axis_w = models.IntegerField(help_text="mm")
    table_dimensions = models.CharField(max_length=100)  # Keep as text, due to complex format
    table_load_capacity = models.IntegerField(help_text="kg")
    spindle_rpm = models.IntegerField(help_text="rpm")
    spindle_type = models.CharField(max_length=50)
    tool_magazine_capacity = models.IntegerField(help_text="adet")
    holder_type = models.CharField(max_length=50)
    rapid_traverse_speed = models.FloatField(help_text="m/dk")
    control_unit = models.CharField(max_length=100)
    drilling_tolerance = models.FloatField(help_text="± mm")
    surface_tolerance = models.FloatField(help_text="± mm")
    production_year = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.machine_type} - {self.model_name}"