from rest_framework import serializers
from .models import BugReport, BugReportAttachment, BugReportMessage


class BugReportAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BugReportAttachment
        fields = ['id', 'file', 'uploaded_at']


class BugReportMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = BugReportMessage
        fields = ['id', 'sender_type', 'sender_name', 'content', 'created_at']

    def get_sender_name(self, obj):
        if obj.sender:
            return obj.sender.get_full_name() or obj.sender.username
        return 'Agent'


class BugReportListSerializer(serializers.ModelSerializer):
    reported_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BugReport
        fields = [
            'id', 'title', 'status', 'repo_target',
            'reported_by_name', 'created_at', 'updated_at',
            'pr_backend_url', 'pr_frontend_url',
        ]

    def get_reported_by_name(self, obj):
        if obj.reported_by:
            return obj.reported_by.get_full_name() or obj.reported_by.username
        return ''


class BugReportDetailSerializer(serializers.ModelSerializer):
    reported_by_name = serializers.SerializerMethodField()
    messages         = BugReportMessageSerializer(many=True, read_only=True)
    attachments      = BugReportAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = BugReport
        fields = [
            'id', 'title', 'description', 'steps', 'page_url', 'page_label',
            'status', 'repo_target', 'reported_by_name', 'created_at',
            'updated_at', 'closed_at', 'pr_backend_url', 'pr_frontend_url',
            'messages', 'attachments',
        ]

    def get_reported_by_name(self, obj):
        if obj.reported_by:
            return obj.reported_by.get_full_name() or obj.reported_by.username
        return ''


class BugReportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BugReport
        fields = ['title', 'description', 'steps', 'page_url', 'page_label']

    def create(self, validated_data):
        validated_data['reported_by'] = self.context['request'].user
        return super().create(validated_data)


class BugReportReplySerializer(serializers.Serializer):
    content = serializers.CharField()
