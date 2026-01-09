from rest_framework import serializers
from tasks.serializers import BaseTimerSerializer


class TimerSerializer(BaseTimerSerializer):
    """
    Extends the BaseTimerSerializer to include fields specific to Operations.
    Note: This works with both legacy Tasks and new Operations via GenericForeignKey.
    """
    # For Operation: accessed via operation.part.job_no
    # For legacy Task: accessed via task.job_no
    job_no = serializers.SerializerMethodField(read_only=True)
    image_no = serializers.SerializerMethodField(read_only=True)
    position_no = serializers.SerializerMethodField(read_only=True)
    quantity = serializers.SerializerMethodField(read_only=True)
    estimated_hours = serializers.DecimalField(source='issue_key.estimated_hours', read_only=True, max_digits=10, decimal_places=2)

    class Meta(BaseTimerSerializer.Meta):
        # Inherit fields from the base and add the new ones
        fields = BaseTimerSerializer.Meta.fields + [
            'job_no', 'image_no', 'position_no', 'quantity', 'estimated_hours'
        ]

    def get_job_no(self, obj):
        """Get job_no from Operation.part or legacy Task"""
        issue = obj.issue_key
        if not issue:
            return None
        # Try Operation first (has 'part' FK)
        if hasattr(issue, 'part') and issue.part:
            return issue.part.job_no
        # Fallback to legacy Task (direct field)
        return getattr(issue, 'job_no', None)

    def get_image_no(self, obj):
        """Get image_no from Operation.part or legacy Task"""
        issue = obj.issue_key
        if not issue:
            return None
        # Try Operation first (has 'part' FK)
        if hasattr(issue, 'part') and issue.part:
            return issue.part.image_no
        # Fallback to legacy Task (direct field)
        return getattr(issue, 'image_no', None)

    def get_position_no(self, obj):
        """Get position_no from Operation.part or legacy Task"""
        issue = obj.issue_key
        if not issue:
            return None
        # Try Operation first (has 'part' FK)
        if hasattr(issue, 'part') and issue.part:
            return issue.part.position_no
        # Fallback to legacy Task (direct field)
        return getattr(issue, 'position_no', None)

    def get_quantity(self, obj):
        """Get quantity from Operation.part or legacy Task"""
        issue = obj.issue_key
        if not issue:
            return None
        # Try Operation first (has 'part' FK)
        if hasattr(issue, 'part') and issue.part:
            return issue.part.quantity
        # Fallback to legacy Task (direct field)
        return getattr(issue, 'quantity', None)


class MachineTimelineSegmentSerializer(serializers.Serializer):
    """
    Serializer for machine timeline segments (from machining.services.timeline).
    Used in MachineTimelineView response.
    """
    start_ms = serializers.IntegerField()
    end_ms = serializers.IntegerField()
    task_key = serializers.CharField(allow_null=True)
    task_name = serializers.CharField(allow_null=True)
    is_hold = serializers.BooleanField()
    category = serializers.CharField()  # "work", "hold", or "idle"
    timer_id = serializers.IntegerField(allow_null=True)
