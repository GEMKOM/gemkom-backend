from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User, Group
from django.utils import timezone

class ApprovalPolicy(models.Model):
    name = models.CharField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)

    # optional matching rules (extend later if needed)
    min_amount_eur = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    max_amount_eur = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    priority_in = models.JSONField(default=list, blank=True)  # e.g. ["normal","urgent"]

    selection_priority = models.PositiveIntegerField(default=100)  # lower wins

    def __str__(self): return self.name


class ApprovalStage(models.Model):
    policy = models.ForeignKey(ApprovalPolicy, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    required_approvals = models.PositiveIntegerField(default=1)  # quorum
    approver_users = models.ManyToManyField(User, blank=True, related_name="approval_stages")
    approver_groups = models.ManyToManyField(Group, blank=True, related_name="approval_stages")

    class Meta:
        unique_together = [("policy", "order")]
        ordering = ["policy", "order"]

    def __str__(self): return f"{self.policy.name} · {self.order} · {self.name}"


class PRApprovalWorkflow(models.Model):
    purchase_request = models.OneToOneField("procurement.PurchaseRequest", on_delete=models.CASCADE, related_name="approval_workflow")
    policy = models.ForeignKey(ApprovalPolicy, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    current_stage_order = models.PositiveIntegerField(default=1)
    is_complete = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)
    snapshot = models.JSONField(default=dict, blank=True)  # stages snapshot for audit

    def __str__(self): return f"WF for {self.purchase_request_id} ({self.policy.name})"


class PRApprovalStageInstance(models.Model):
    workflow = models.ForeignKey(PRApprovalWorkflow, on_delete=models.CASCADE, related_name="stage_instances")
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

    def __str__(self): return f"{self.workflow_id} · stage {self.order}"


class PRApprovalDecision(models.Model):
    stage_instance = models.ForeignKey(PRApprovalStageInstance, on_delete=models.CASCADE, related_name="decisions")
    approver = models.ForeignKey(User, on_delete=models.PROTECT)
    decision = models.CharField(max_length=10, choices=[("approve","Approve"),("reject","Reject")])
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("stage_instance", "approver")]
        ordering = ["decided_at"]
