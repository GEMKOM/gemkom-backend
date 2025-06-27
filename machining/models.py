from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User

class Timer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='started_timers')
    stopped_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='stopped_timers')
    issue_key = models.CharField(max_length=255)
    start_time = models.BigIntegerField()
    finish_time = models.BigIntegerField(null=True, blank=True)
    synced_to_jira = models.BooleanField(default=False)
    manual_entry = models.BooleanField(default=False)
    comment = models.TextField(null=True, blank=True)
    machine = models.CharField(max_length=255, null=True, blank=True)
    job_no = models.CharField(max_length=255, null=True, blank=True)
    image_no = models.CharField(max_length=255, null=True, blank=True)
    position_no = models.CharField(max_length=255, null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    

    class Meta:
        ordering = ['-start_time']