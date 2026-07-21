from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey


#NEW
class ApprovalWorkflow(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    subject = GenericForeignKey("content_type", "object_id")

    # Reuse your existing ApprovalPolicy records
    policy = models.ForeignKey("approvals.ApprovalPolicy", on_delete=models.PROTECT)

    created_at = models.DateTimeField(auto_now_add=True)
    current_stage_order = models.PositiveIntegerField(default=1)
    is_complete = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["content_type", "object_id"])]

class ApprovalStageInstance(models.Model):
    workflow = models.ForeignKey(ApprovalWorkflow, on_delete=models.CASCADE, related_name="stage_instances")
    order = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    required_approvals = models.PositiveIntegerField(default=1)
    approver_user_ids = models.JSONField(default=list, blank=True)
    approver_group_ids = models.JSONField(default=list, blank=True)
    approved_count = models.PositiveIntegerField(default=0)
    is_complete = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)

    class Meta:
        unique_together = [("workflow", "order")]
        ordering = ["order"]

class ApprovalDecision(models.Model):
    stage_instance = models.ForeignKey(ApprovalStageInstance, on_delete=models.CASCADE, related_name="decisions")
    approver = models.ForeignKey(User, on_delete=models.PROTECT)
    decision = models.CharField(max_length=10, choices=[("approve","Approve"),("reject","Reject")])
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("stage_instance", "approver")]
        ordering = ["decided_at"]


class ApprovalPolicy(models.Model):
    SUBJECT_CHOICES = [
        ("vacation_request",              "Vacation Request"),
        ("overtime_request",              "Overtime Request"),
        ("purchase_request",              "Purchase Request"),
        ("purchase_request_rolling_mill", "Purchase Request (Rolling Mill)"),
        ("subcontractor_statement",       "Subcontractor Statement"),
        ("qc_review",                     "QC Review"),
        ("ncr",                           "NCR"),
        ("sales_offer",                   "Sales Offer"),
        ("department_request",            "Department Request"),
        ("crane_request",                 "Crane Request"),
    ]

    name = models.CharField(max_length=200, unique=True)
    subject_type = models.SlugField(
        max_length=50, blank=True, default='',
        help_text="Which workflow subject this policy applies to. Used for policy lookup; renaming the policy will not break routing.",
    )
    is_active = models.BooleanField(default=True)

    # optional matching rules (extend later if needed)
    min_amount_eur = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    max_amount_eur = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    selection_priority = models.PositiveIntegerField(default=100)  # lower wins

    def __str__(self): return self.name


class ApprovalStage(models.Model):
    policy = models.ForeignKey(ApprovalPolicy, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    required_approvals = models.PositiveIntegerField(default=1)  # quorum

    # Static overrides — directors/owners and explicit assignments go here
    approver_users = models.ManyToManyField(User, blank=True, related_name="approval_stages")

    # Org-tree dynamic resolution
    climb_levels = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Walk N levels up the requester's position tree to find approvers. Vacant positions are skipped.",
    )
    role_user_group = models.ForeignKey(
        'organization.UserGroup',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='approval_stages',
        help_text="When set, resolve approvers to all active members of this UserGroup (ignores climb_levels).",
    )

    class Meta:
        unique_together = [("policy", "order")]
        ordering = ["policy", "order"]

    def __str__(self): return f"{self.policy.name} · {self.order} · {self.name}"
