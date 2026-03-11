from rest_framework import serializers
from .models import Notification, NotificationPreference
from .service import NOTIFICATION_DEFAULTS


class NotificationSerializer(serializers.ModelSerializer):
    notification_type_display = serializers.CharField(
        source='get_notification_type_display', read_only=True
    )

    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_type',
            'notification_type_display',
            'title',
            'body',
            'link',
            'source_type',
            'source_id',
            'is_read',
            'read_at',
            'is_emailed',
            'created_at',
        ]
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    is_default = serializers.BooleanField(read_only=True, default=False)
    notification_type_display = serializers.SerializerMethodField()

    class Meta:
        model = NotificationPreference
        fields = ['id', 'notification_type', 'notification_type_display', 'send_email', 'send_in_app', 'is_default']
        read_only_fields = ['id', 'notification_type', 'notification_type_display', 'is_default']

    def get_notification_type_display(self, obj):
        # Works for both model instances and plain dicts (returned from list endpoint for defaults)
        if isinstance(obj, dict):
            ntype = obj.get('notification_type', '')
        else:
            ntype = obj.notification_type
        choices = dict(Notification.NOTIFICATION_TYPE_CHOICES)
        return choices.get(ntype, ntype)
