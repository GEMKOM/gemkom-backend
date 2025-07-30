from django.db import models
from django.contrib.auth.models import User

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
        ('warehouse', 'Ambar')
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
    is_lead = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    must_reset_password = models.BooleanField(default=False)
    jira_api_token = models.CharField(max_length=255, blank=True, null=True)
    occupation = models.CharField(max_length=50, choices=OCCUPATION_CHOICES, null=True, blank=True)
    COLLAR_TYPES = [
        ('blue', 'Mavi Yaka'),
        ('white', 'Beyaz Yaka'),
    ]
    collar_type = models.CharField(max_length=10, choices=COLLAR_TYPES, default='blue')

    def __str__(self):
        return self.user.username
