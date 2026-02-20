from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import QCReview, NCR

User = get_user_model()


# =============================================================================
# QCReview serializers
# =============================================================================

class QCReviewListSerializer(serializers.ModelSerializer):
    submitted_by_name = serializers.CharField(source='submitted_by.get_full_name', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True, default=None)
    task_title = serializers.CharField(source='task.title', read_only=True)
    job_order = serializers.CharField(source='task.job_order_id', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = QCReview
        fields = [
            'id', 'task', 'task_title', 'job_order',
            'submitted_by', 'submitted_by_name', 'submitted_at',
            'status', 'status_display',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at',
            'comment', 'part_data', 'ncr',
        ]


class QCReviewDetailSerializer(serializers.ModelSerializer):
    submitted_by_name = serializers.CharField(source='submitted_by.get_full_name', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True, default=None)
    task_title = serializers.CharField(source='task.title', read_only=True)
    task_department = serializers.CharField(source='task.department', read_only=True)
    job_order = serializers.CharField(source='task.job_order_id', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = QCReview
        fields = [
            'id', 'task', 'task_title', 'task_department', 'job_order',
            'submitted_by', 'submitted_by_name', 'submitted_at',
            'status', 'status_display',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at',
            'comment', 'part_data', 'ncr',
        ]
        read_only_fields = [
            'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at', 'status', 'ncr',
        ]


class QCReviewSubmitSerializer(serializers.Serializer):
    """Input for submitting a task to QC review."""
    task_id = serializers.IntegerField()
    part_data = serializers.JSONField(required=False, default=dict)

    def validate_task_id(self, value):
        from projects.models import JobOrderDepartmentTask
        try:
            return JobOrderDepartmentTask.objects.get(pk=value)
        except JobOrderDepartmentTask.DoesNotExist:
            raise serializers.ValidationError("Geçersiz görev ID.")


class QCReviewBulkSubmitSerializer(serializers.Serializer):
    """
    Input for bulk-submitting multiple QC reviews for a single task.
    Each item in `reviews` becomes one QCReview with its own part_data.
    """
    task_id = serializers.IntegerField()
    reviews = serializers.ListField(
        child=serializers.JSONField(default=dict),
        min_length=1,
    )

    def validate_task_id(self, value):
        from projects.models import JobOrderDepartmentTask
        try:
            return JobOrderDepartmentTask.objects.get(pk=value)
        except JobOrderDepartmentTask.DoesNotExist:
            raise serializers.ValidationError("Geçersiz görev ID.")

    def validate_reviews(self, value):
        if not value:
            raise serializers.ValidationError("En az bir inceleme gereklidir.")
        return value


class QCDecisionSerializer(serializers.Serializer):
    """
    Input for a QC team member to approve or reject a review.
    On rejection, the optional ncr_* fields prefill the auto-created NCR.
    """
    approve = serializers.BooleanField()
    comment = serializers.CharField(required=False, allow_blank=True, default='')

    # NCR prefill fields — only used when approve=False
    ncr_title = serializers.CharField(required=False, allow_blank=True, default='')
    ncr_description = serializers.CharField(required=False, allow_blank=True, default='')
    ncr_defect_type = serializers.ChoiceField(
        choices=[c[0] for c in NCR.DEFECT_TYPE_CHOICES],
        required=False,
        default='other',
    )
    ncr_severity = serializers.ChoiceField(
        choices=[c[0] for c in NCR.SEVERITY_CHOICES],
        required=False,
        default='minor',
    )
    ncr_affected_quantity = serializers.IntegerField(required=False, min_value=1, default=1)
    ncr_disposition = serializers.ChoiceField(
        choices=[c[0] for c in NCR.DISPOSITION_CHOICES],
        required=False,
        default='pending',
    )


# =============================================================================
# NCR serializers
# =============================================================================

class NCRListSerializer(serializers.ModelSerializer):
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    defect_type_display = serializers.CharField(source='get_defect_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)

    class Meta:
        model = NCR
        fields = [
            'id', 'ncr_number', 'title',
            'job_order', 'job_order_title',
            'department_task',
            'severity', 'severity_display',
            'defect_type', 'defect_type_display',
            'status', 'status_display',
            'assigned_team', 'disposition',
            'submission_count',
            'created_by', 'created_by_name', 'created_at',
        ]


class NCRDetailSerializer(serializers.ModelSerializer):
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    defect_type_display = serializers.CharField(source='get_defect_type_display', read_only=True)
    disposition_display = serializers.CharField(source='get_disposition_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    detected_by_name = serializers.CharField(source='detected_by.get_full_name', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    assigned_members_data = serializers.SerializerMethodField()

    class Meta:
        model = NCR
        fields = [
            'id', 'ncr_number', 'title', 'description',
            'job_order', 'job_order_title',
            'department_task', 'qc_review',
            'defect_type', 'defect_type_display',
            'severity', 'severity_display',
            'detected_by', 'detected_by_name',
            'affected_quantity',
            'root_cause', 'corrective_action',
            'disposition', 'disposition_display',
            'assigned_team', 'assigned_members', 'assigned_members_data',
            'status', 'status_display',
            'submission_count',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['ncr_number', 'submission_count', 'created_by', 'created_at', 'updated_at']

    def get_assigned_members_data(self, obj):
        return [
            {'id': u.id, 'name': u.get_full_name(), 'email': u.email}
            for u in obj.assigned_members.all()
        ]


class NCRCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NCR
        fields = [
            'job_order', 'department_task', 'qc_review',
            'title', 'description',
            'defect_type', 'severity',
            'detected_by', 'affected_quantity',
            'assigned_team', 'assigned_members',
            'disposition',
        ]

    def validate(self, attrs):
        if not attrs.get('job_order'):
            raise serializers.ValidationError({'job_order': 'İş emri zorunludur.'})
        return attrs


class NCRUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NCR
        fields = [
            'title', 'description',
            'defect_type', 'severity',
            'detected_by', 'affected_quantity',
            'root_cause', 'corrective_action', 'disposition',
            'assigned_team', 'assigned_members',
        ]


class NCRSubmitSerializer(serializers.ModelSerializer):
    """
    Optional field updates sent alongside an NCR submission (or resubmission).
    All fields are optional — only provided fields are saved before the workflow is created.
    """
    class Meta:
        model = NCR
        fields = ['root_cause', 'corrective_action', 'disposition']
        extra_kwargs = {
            'root_cause': {'required': False},
            'corrective_action': {'required': False},
            'disposition': {'required': False},
        }


class NCRDecisionSerializer(serializers.Serializer):
    """Input for a QC team member to approve or reject an NCR."""
    approve = serializers.BooleanField()
    comment = serializers.CharField(required=False, allow_blank=True, default='')
