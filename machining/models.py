from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User

from machines.models import Machine

class Task(models.Model):
    key = models.CharField(max_length=255, primary_key=True)  # Matches Timer.issue_key
    name = models.CharField(max_length=255)
    job_no = models.CharField(max_length=255, null=True, blank=True)
    image_no = models.CharField(max_length=255, null=True, blank=True)
    position_no = models.CharField(max_length=255, null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    completed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    completion_date = models.BigIntegerField(null=True, blank=True)

    def __str__(self):
        return self.name
    

class Timer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='started_timers')
    stopped_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='stopped_timers')
    issue_key = models.ForeignKey(Task, on_delete=models.CASCADE, to_field='key', db_column='issue_key', related_name='timers')
    start_time = models.BigIntegerField()
    finish_time = models.BigIntegerField(null=True, blank=True)
    synced_to_jira = models.BooleanField(default=False)
    manual_entry = models.BooleanField(default=False)
    comment = models.TextField(null=True, blank=True)
    machine = models.CharField(max_length=255, null=True, blank=True)
    machine_fk = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name='machine_timers')
    

    class Meta:
        ordering = ['-start_time']

