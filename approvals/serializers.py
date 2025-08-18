from rest_framework import serializers
from .models import PRApprovalWorkflow, PRApprovalStageInstance, PRApprovalDecision

class DecisionSerializer(serializers.ModelSerializer):
    approver_username = serializers.CharField(source="approver.username", read_only=True)
    class Meta:
        model = PRApprovalDecision
        fields = ["id","approver","approver_username","decision","comment","decided_at"]

class StageInstanceSerializer(serializers.ModelSerializer):
    decisions = DecisionSerializer(many=True, read_only=True)
    class Meta:
        model = PRApprovalStageInstance
        fields = ["order","name","required_approvals","approved_count","is_complete","is_rejected","approver_user_ids","decisions"]

class WorkflowSerializer(serializers.ModelSerializer):
    stage_instances = StageInstanceSerializer(many=True, read_only=True)
    class Meta:
        model = PRApprovalWorkflow
        fields = ["policy","current_stage_order","is_complete","is_rejected","stage_instances"]
