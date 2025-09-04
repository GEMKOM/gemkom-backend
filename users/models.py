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
        ('management', 'Yönetim')
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
    jira_api_token = models.CharField(max_length=255, blank=True, null=True)
    occupation = models.CharField(max_length=50, choices=OCCUPATION_CHOICES, null=True, blank=True)
    location_type = [
        ('workshop', 'Atölye'),
        ('office', 'Ofis'),
    ]
    work_location = models.CharField(max_length=10, choices=location_type, default='workshop')

    def __str__(self):
        return self.user.username
    
    @property
    def is_admin(self) -> bool:
        return bool(getattr(self.user, "is_superuser", False) or self.work_location == "office")

def _user_is_admin(self) -> bool:
    # guards AnonymousUser and missing profile
    if not getattr(self, "is_authenticated", False):
        return False
    if getattr(self, "is_superuser", False):
        return True
    prof = getattr(self, "profile", None)
    return bool(prof and getattr(prof, "work_location", None) == "office")

# attach as a property
User.add_to_class("is_admin", property(_user_is_admin))