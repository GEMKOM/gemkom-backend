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
        ('rollingmill', 'Haddehane')
        # Add more as needed
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    team = models.CharField(max_length=50, choices=TEAM_CHOICES, null=True, blank=True)
    is_lead = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    must_reset_password = models.BooleanField(default=False)
    jira_api_token = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.user.username
