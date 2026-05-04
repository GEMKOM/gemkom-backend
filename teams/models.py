from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    foreman = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='foreman_of_teams',
    )
    members = models.ManyToManyField(
        User,
        blank=True,
        related_name='teams',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Ekip'
        verbose_name_plural = 'Ekipler'

    def __str__(self):
        return self.name
