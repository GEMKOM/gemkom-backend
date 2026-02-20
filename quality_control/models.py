from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation

from approvals.models import ApprovalWorkflow
from projects.models import JobOrder, JobOrderDepartmentTask


# =============================================================================
# QCReview — task-level quality control review
# =============================================================================

class QCReview(models.Model):
    STATUS_CHOICES = [
        ('pending', 'İnceleme Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
    ]

    task = models.ForeignKey(
        JobOrderDepartmentTask,
        on_delete=models.CASCADE,
        related_name='qc_reviews'
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='submitted_qc_reviews'
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_qc_reviews'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

    # Free-form part data submitted with the review (location, quantity, drawing no, position no, etc.)
    part_data = models.JSONField(default=dict, blank=True)

    # Auto-linked NCR on rejection (FK in reverse; we also add a direct FK for convenience)
    ncr = models.ForeignKey(
        'NCR',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_reviews'
    )

    # Generic relation so the approval engine can find this review's workflow
    approvals = GenericRelation(
        ApprovalWorkflow,
        related_query_name='qc_review'
    )

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['task', 'status']),
            models.Index(fields=['status', 'submitted_at']),
        ]
        verbose_name = 'KK İncelemesi'
        verbose_name_plural = 'KK İncelemeleri'

    def __str__(self):
        return f"QCReview #{self.id} — {self.task} ({self.status})"

    def handle_approval_event(self, workflow, event: str, payload: dict):
        """
        Called by the generic approval engine (_notify_subject) after a decision.
        Actual side effects are handled in the approval_service to keep them
        inside the same transaction.atomic block as the decision.
        """
        from quality_control.approval_service import (
            _on_qc_review_approved,
            _on_qc_review_rejected,
        )
        if event == 'approved':
            _on_qc_review_approved(self)
        elif event == 'rejected':
            _on_qc_review_rejected(self, comment=payload.get('comment', ''))


# =============================================================================
# NCR — Non-Conformance Report
# =============================================================================

class NCR(models.Model):
    DEFECT_TYPE_CHOICES = [
        ('dimensional', 'Boyutsal'),
        ('surface', 'Yüzey'),
        ('material', 'Malzeme'),
        ('welding', 'Kaynak'),
        ('machining', 'Talaşlı İmalat'),
        ('assembly', 'Montaj'),
        ('documentation', 'Dokümantasyon'),
        ('other', 'Diğer'),
    ]

    SEVERITY_CHOICES = [
        ('minor', 'Minör'),
        ('major', 'Majör'),
        ('critical', 'Kritik'),
    ]

    DISPOSITION_CHOICES = [
        ('rework', 'Yeniden İşleme'),
        ('scrap', 'Hurda'),
        ('accept_as_is', 'Olduğu Gibi Kabul'),
        ('pending', 'Karar Bekliyor'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Aksiyon Bekliyor'),
        ('submitted', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
        ('closed', 'Kapatıldı'),
    ]

    # Identification
    ncr_number = models.CharField(max_length=50, unique=True, db_index=True)

    # Links — job_order is always required; task and review are optional
    job_order = models.ForeignKey(
        JobOrder,
        on_delete=models.PROTECT,
        related_name='ncrs'
    )
    department_task = models.ForeignKey(
        JobOrderDepartmentTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ncrs'
    )
    qc_review = models.ForeignKey(
        'QCReview',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ncrs'
    )

    # Core fields
    title = models.CharField(max_length=255)
    description = models.TextField()
    defect_type = models.CharField(
        max_length=30,
        choices=DEFECT_TYPE_CHOICES,
        default='other'
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default='minor',
        db_index=True
    )
    detected_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='detected_ncrs'
    )
    affected_quantity = models.PositiveIntegerField(default=1)

    # Resolution fields (filled later)
    root_cause = models.TextField(blank=True)
    corrective_action = models.TextField(blank=True)
    disposition = models.CharField(
        max_length=20,
        choices=DISPOSITION_CHOICES,
        default='pending'
    )

    # Assignment
    assigned_team = models.CharField(max_length=50, blank=True)
    assigned_members = models.ManyToManyField(
        User,
        blank=True,
        related_name='assigned_ncrs'
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True
    )
    submission_count = models.PositiveIntegerField(default=0)

    # Generic relation for approval workflow
    approvals = GenericRelation(
        ApprovalWorkflow,
        related_query_name='ncr'
    )

    # Audit
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='created_ncrs'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job_order', 'status']),
            models.Index(fields=['severity', 'status']),
            models.Index(fields=['assigned_team', 'status']),
        ]
        verbose_name = 'Uygunsuzluk Raporu'
        verbose_name_plural = 'Uygunsuzluk Raporları'

    def __str__(self):
        return f"{self.ncr_number} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.ncr_number:
            self.ncr_number = self._generate_ncr_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_ncr_number() -> str:
        """Generate NCR-{year}-{seq:04d} sequentially per year."""
        from django.utils import timezone as tz
        year = tz.now().year
        prefix = f"NCR-{year}-"
        last = (
            NCR.objects
            .filter(ncr_number__startswith=prefix)
            .order_by('-ncr_number')
            .values_list('ncr_number', flat=True)
            .first()
        )
        if last:
            try:
                seq = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    def handle_approval_event(self, workflow, event: str, payload: dict):
        """Called by the generic approval engine after a decision on this NCR."""
        from quality_control.approval_service import (
            _on_ncr_approved,
            _on_ncr_rejected,
        )
        if event == 'approved':
            _on_ncr_approved(self)
        elif event == 'rejected':
            _on_ncr_rejected(self, comment=payload.get('comment', ''))
