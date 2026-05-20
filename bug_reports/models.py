from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class BugReport(models.Model):
    STATUS_OPEN         = 'open'
    STATUS_WAITING      = 'waiting_info'
    STATUS_IN_PROGRESS  = 'in_progress'
    STATUS_PR_CREATED   = 'pr_created'
    STATUS_ESCALATED    = 'escalated'
    STATUS_CLOSED       = 'closed'
    STATUS_CHOICES = [
        (STATUS_OPEN,        'Open'),
        (STATUS_WAITING,     'Waiting for Info'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_PR_CREATED,  'PR Created'),
        (STATUS_ESCALATED,   'Escalated to Staff'),
        (STATUS_CLOSED,      'Closed'),
    ]

    REPO_BACKEND  = 'backend'
    REPO_FRONTEND = 'frontend'
    REPO_BOTH     = 'both'
    REPO_UNKNOWN  = 'unknown'
    REPO_CHOICES = [
        (REPO_BACKEND,  'Backend'),
        (REPO_FRONTEND, 'Frontend'),
        (REPO_BOTH,     'Both'),
        (REPO_UNKNOWN,  'Unknown'),
    ]

    title           = models.CharField(max_length=255)
    description     = models.TextField()
    steps           = models.TextField(blank=True, help_text='Steps to reproduce')
    page_url        = models.CharField(max_length=255, blank=True, help_text='Frontend route where the bug occurred')
    page_label      = models.CharField(max_length=255, blank=True, help_text='Human-readable page name')
    reported_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='bug_reports')
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    repo_target     = models.CharField(max_length=20, choices=REPO_CHOICES, default=REPO_UNKNOWN)
    pr_backend_url  = models.URLField(blank=True)
    pr_frontend_url = models.URLField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    closed_at       = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'#{self.pk} {self.title}'

    def close(self):
        self.status = self.STATUS_CLOSED
        self.closed_at = timezone.now()
        self.save(update_fields=['status', 'closed_at', 'updated_at'])


class BugReportAttachment(models.Model):
    bug_report  = models.ForeignKey(BugReport, on_delete=models.CASCADE, related_name='attachments')
    file        = models.FileField(upload_to='bug_reports/attachments/')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Attachment for #{self.bug_report_id}'


class BugReportMessage(models.Model):
    SENDER_USER  = 'user'
    SENDER_AGENT = 'agent'
    SENDER_CHOICES = [
        (SENDER_USER,  'User'),
        (SENDER_AGENT, 'Agent'),
    ]

    bug_report  = models.ForeignKey(BugReport, on_delete=models.CASCADE, related_name='messages')
    sender_type = models.CharField(max_length=10, choices=SENDER_CHOICES)
    sender      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    content     = models.TextField()
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.sender_type} message on #{self.bug_report_id}'
