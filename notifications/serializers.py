from rest_framework import serializers
from .models import Notification, NotificationPreference, NotificationRoute
from .service import NOTIFICATION_DEFAULTS
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
        # Works for both model instances and plain dicts (returned from list endpoint for defaults)
        if isinstance(obj, dict):
            ntype = obj.get('notification_type', '')
        else:
            ntype = obj.notification_type
        choices = dict(Notification.NOTIFICATION_TYPE_CHOICES)
        return choices.get(ntype, ntype)


class NotificationRouteUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(read_only=True)

    def get_full_name(self, obj):
        return obj.get_full_name()


# Describes who always gets notified regardless of route configuration.
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


class NotificationRouteSerializer(serializers.ModelSerializer):
    notification_type_display = serializers.SerializerMethodField()
    always_notified = serializers.SerializerMethodField()
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
        return NotificationRouteUserSerializer(obj.users.all(), many=True).data

    def validate_teams(self, value):
        invalid = set(value) - _VALID_TEAMS
        if invalid:
            raise serializers.ValidationError(f"Geçersiz ekip(ler): {', '.join(invalid)}")
        return value

    class Meta:
        model = NotificationRoute
        fields = [
            'notification_type', 'notification_type_display',
            'always_notified',
            'users', 'user_ids',
            'teams',
            'link',
            'enabled',
        ]

    def get_notification_type_display(self, obj):
        choices = dict(Notification.NOTIFICATION_TYPE_CHOICES)
        return choices.get(obj.notification_type, obj.notification_type)

    def get_always_notified(self, obj):
        return ALWAYS_NOTIFIED.get(obj.notification_type)

    def update(self, instance, validated_data):
        user_ids = validated_data.pop('user_ids', None)
        instance.enabled = validated_data.get('enabled', instance.enabled)
        instance.link = validated_data.get('link', instance.link)
        instance.teams = validated_data.get('teams', instance.teams)
        instance.save(update_fields=['enabled', 'link', 'teams'])
        if user_ids is not None:
            from django.contrib.auth.models import User
            instance.users.set(User.objects.filter(id__in=user_ids, is_active=True))
        return instance
