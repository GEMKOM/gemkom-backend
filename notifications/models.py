from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    # -------------------------------------------------------------------------
    # Type constants
    # -------------------------------------------------------------------------

    # Procurement
    PR_APPROVAL_REQUESTED    = 'pr_approval_requested'
    PR_APPROVED              = 'pr_approved'
    PR_REJECTED              = 'pr_rejected'
    PR_PO_CREATED            = 'pr_po_created'
    # Overtime
    OT_APPROVAL_REQUESTED    = 'ot_approval_requested'
    OT_APPROVED              = 'ot_approved'
    OT_REJECTED              = 'ot_rejected'
    # QC Reviews
    QC_REVIEW_SUBMITTED      = 'qc_review_submitted'
    QC_REVIEW_APPROVED       = 'qc_review_approved'
    QC_REVIEW_REJECTED       = 'qc_review_rejected'
    # NCR
    NCR_CREATED              = 'ncr_created'
    NCR_SUBMITTED            = 'ncr_submitted'
    NCR_APPROVED             = 'ncr_approved'
    NCR_REJECTED             = 'ncr_rejected'
    NCR_ASSIGNED             = 'ncr_assigned'
    # Sales
    SALES_APPROVAL_REQUESTED = 'sales_approval_requested'
    SALES_APPROVED           = 'sales_approved'
    SALES_REJECTED           = 'sales_rejected'
    SALES_CONSULTATION       = 'sales_consultation'
    SALES_CONVERTED          = 'sales_converted'
    # Subcontracting
    SUB_APPROVAL_REQUESTED   = 'sub_approval_requested'
    SUB_APPROVED             = 'sub_approved'
    SUB_REJECTED             = 'sub_rejected'
    # Planning / Department Requests
    PLAN_APPROVAL_REQUESTED  = 'plan_approval_requested'
    PLAN_APPROVED            = 'plan_approved'
    PLAN_REJECTED            = 'plan_rejected'
    PLAN_DR_APPROVED         = 'plan_dr_approved'
    # Drawing workflow
    DRAWING_RELEASED         = 'drawing_released'
    REVISION_REQUESTED       = 'revision_requested'
    REVISION_APPROVED        = 'revision_approved'
    REVISION_COMPLETED       = 'revision_completed'
    REVISION_REJECTED        = 'revision_rejected'
    JOB_ON_HOLD              = 'job_on_hold'
    JOB_RESUMED              = 'job_resumed'
    # Discussions
    TOPIC_MENTION            = 'topic_mention'
    COMMENT_MENTION          = 'comment_mention'
    NEW_COMMENT              = 'new_comment'
    # Auth
    PASSWORD_RESET           = 'password_reset'

    NOTIFICATION_TYPE_CHOICES = [
        (PR_APPROVAL_REQUESTED,    'Satınalma Onayı Bekleniyor'),
        (PR_APPROVED,              'Satınalma Talebi Onaylandı'),
        (PR_REJECTED,              'Satınalma Talebi Reddedildi'),
        (PR_PO_CREATED,            'Satınalma Siparişi Oluşturuldu'),
        (OT_APPROVAL_REQUESTED,    'Mesai Onayı Bekleniyor'),
        (OT_APPROVED,              'Mesai Talebi Onaylandı'),
        (OT_REJECTED,              'Mesai Talebi Reddedildi'),
        (QC_REVIEW_SUBMITTED,      'KK İncelemesi Gönderildi'),
        (QC_REVIEW_APPROVED,       'KK İncelemesi Onaylandı'),
        (QC_REVIEW_REJECTED,       'KK İncelemesi Reddedildi'),
        (NCR_CREATED,              'NCR Oluşturuldu'),
        (NCR_SUBMITTED,            'NCR Onaya Gönderildi'),
        (NCR_APPROVED,             'NCR Onaylandı'),
        (NCR_REJECTED,             'NCR Reddedildi'),
        (NCR_ASSIGNED,             'NCR Atandı'),
        (SALES_APPROVAL_REQUESTED, 'Satış Teklifi Onay Bekliyor'),
        (SALES_APPROVED,           'Satış Teklifi Onaylandı'),
        (SALES_REJECTED,           'Satış Teklifi Reddedildi'),
        (SALES_CONSULTATION,       'Satış Danışma Talebi'),
        (SALES_CONVERTED,          'Teklif İş Emrine Dönüştürüldü'),
        (SUB_APPROVAL_REQUESTED,   'Taşeron Hakedişi Onay Bekliyor'),
        (SUB_APPROVED,             'Taşeron Hakedişi Onaylandı'),
        (SUB_REJECTED,             'Taşeron Hakedişi Reddedildi'),
        (PLAN_APPROVAL_REQUESTED,  'Departman Talebi Onay Bekliyor'),
        (PLAN_APPROVED,            'Departman Talebi Onaylandı'),
        (PLAN_REJECTED,            'Departman Talebi Reddedildi'),
        (PLAN_DR_APPROVED,         'Departman Talebi Planlama Onayladı'),
        (DRAWING_RELEASED,         'Çizim Yayınlandı'),
        (REVISION_REQUESTED,       'Revizyon Talep Edildi'),
        (REVISION_APPROVED,        'Revizyon Onaylandı'),
        (REVISION_COMPLETED,       'Revizyon Tamamlandı'),
        (REVISION_REJECTED,        'Revizyon Reddedildi'),
        (JOB_ON_HOLD,              'İş Beklemede'),
        (JOB_RESUMED,              'İş Devam Ediyor'),
        (TOPIC_MENTION,            'Konuda Etiketlendiniz'),
        (COMMENT_MENTION,          'Yorumda Etiketlendiniz'),
        (NEW_COMMENT,              'Yeni Yorum'),
        (PASSWORD_RESET,           'Parola Sıfırlama Talebi'),
    ]

    # -------------------------------------------------------------------------
    # Fields
    # -------------------------------------------------------------------------
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(
        max_length=60,
        choices=NOTIFICATION_TYPE_CHOICES,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    body  = models.TextField(blank=True)
    link  = models.CharField(max_length=500, blank=True)

    # Optional reference to the triggering object (no GenericFK overhead)
    source_type = models.CharField(max_length=50, blank=True)   # e.g. 'purchase_request'
    source_id   = models.PositiveIntegerField(null=True, blank=True)

    # Read status
    is_read  = models.BooleanField(default=False, db_index=True)
    read_at  = models.DateTimeField(null=True, blank=True)

    # Email delivery tracking
    is_emailed  = models.BooleanField(default=False)
    emailed_at  = models.DateTimeField(null=True, blank=True)
    email_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'notification_type', 'created_at']),
        ]

    def __str__(self):
        return f'{self.user_id} | {self.notification_type} | {self.created_at:%Y-%m-%d %H:%M}'

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class NotificationPreference(models.Model):
    """
    Per-user, per-type preference row.
    Rows are only created when the user overrides the default.
    Missing rows fall back to NOTIFICATION_DEFAULTS in service.py.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences',
    )
    notification_type = models.CharField(max_length=60, db_index=True)
    send_email        = models.BooleanField(default=True)
    send_in_app       = models.BooleanField(default=True)

    class Meta:
        unique_together = [('user', 'notification_type')]

    def __str__(self):
        return f'{self.user_id} | {self.notification_type}'
