from rest_framework import serializers
from .models import Notification, NotificationPreference, NotificationConfig
from .service import NOTIFICATION_DEFAULTS, NOTIFICATION_CONFIG_DEFAULTS
from users.models import UserProfile

_VALID_TEAMS = {v for v, _ in UserProfile.TEAM_CHOICES}
TEAM_CHOICES = [{'value': v, 'label': l} for v, l in UserProfile.TEAM_CHOICES]


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
            'emailed_at',
            'email_error',
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
        if isinstance(obj, dict):
            ntype = obj.get('notification_type', '')
        else:
            ntype = obj.notification_type
        choices = dict(Notification.NOTIFICATION_TYPE_CHOICES)
        return choices.get(ntype, ntype)


# Describes who always gets notified regardless of config routing.
ALWAYS_NOTIFIED = {
    Notification.SALES_CONVERTED:    None,
    Notification.SALES_CONSULTATION: 'Danışma görevi atanan kişiler',
    Notification.JOB_ON_HOLD:        'İş emrindeki tüm görev sorumluları',
    Notification.JOB_RESUMED:        'İş emrindeki tüm görev sorumluları',
    Notification.DRAWING_RELEASED:   'Konudaki @bahsedilen kullanıcılar',
    Notification.REVISION_REQUESTED: 'Tasarım görev sorumlusu ve mevcut yayımcı',
    Notification.REVISION_APPROVED:  'Revizyon talebini açan kişi',
    Notification.REVISION_COMPLETED: 'Orijinal revizyon talepcisi ve @bahsedilen kullanıcılar',
    Notification.REVISION_REJECTED:  'Revizyon talebini açan kişi',
}


class NotificationConfigUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(read_only=True)

    def get_full_name(self, obj):
        return obj.get_full_name()


class NotificationConfigSerializer(serializers.ModelSerializer):
    notification_type_display = serializers.SerializerMethodField()
    always_notified = serializers.SerializerMethodField()
    is_routable = serializers.SerializerMethodField()
    users = serializers.SerializerMethodField()
    user_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    teams = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )

    def get_users(self, obj):
        if not obj.pk:
            return []
        return NotificationConfigUserSerializer(obj.users.all(), many=True).data

    def get_notification_type_display(self, obj):
        if isinstance(obj, dict):
            ntype = obj.get('notification_type', '')
        else:
            ntype = obj.notification_type
        choices = dict(Notification.NOTIFICATION_TYPE_CHOICES)
        return choices.get(ntype, ntype)

    def get_always_notified(self, obj):
        ntype = obj.get('notification_type') if isinstance(obj, dict) else obj.notification_type
        return ALWAYS_NOTIFIED.get(ntype)

    def get_is_routable(self, obj):
        ntype = obj.get('notification_type') if isinstance(obj, dict) else obj.notification_type
        return ntype in NotificationConfig.ROUTABLE_TYPES

    def validate_teams(self, value):
        invalid = set(value) - _VALID_TEAMS
        if invalid:
            raise serializers.ValidationError(f"Geçersiz ekip(ler): {', '.join(invalid)}")
        return value

    class Meta:
        model = NotificationConfig
        fields = [
            'notification_type',
            'notification_type_display',
            'title_template',
            'body_template',
            'link_template',
            'available_vars',
            'updated_at',
            'always_notified',
            'is_routable',
            'users',
            'user_ids',
            'teams',
            'enabled',
        ]
        read_only_fields = ['notification_type', 'available_vars', 'updated_at']

    def update(self, instance, validated_data):
        user_ids = validated_data.pop('user_ids', None)
        for attr in ('title_template', 'body_template', 'link_template', 'teams', 'enabled'):
            if attr in validated_data:
                setattr(instance, attr, validated_data[attr])
        instance.save()
        if user_ids is not None:
            from django.contrib.auth.models import User
            instance.users.set(User.objects.filter(id__in=user_ids, is_active=True))
        return instance
