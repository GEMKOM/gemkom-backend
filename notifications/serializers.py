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
    # Discussions
    Notification.TOPIC_MENTION:          'Konuda @etiketlenen kullanıcılar',
    Notification.COMMENT_MENTION:        'Yorumda @etiketlenen kullanıcılar',
    Notification.NEW_COMMENT:            'Konuya daha önce yorum yapan veya konuyu açan kullanıcılar',
    # Drawing workflow
    Notification.DRAWING_RELEASED:       'Konudaki @bahsedilen kullanıcılar',
    Notification.REVISION_REQUESTED:     'Tasarım görev sorumlusu ve mevcut yayımcı',
    Notification.REVISION_APPROVED:      'Revizyon talebini açan kişi',
    Notification.REVISION_COMPLETED:     'Orijinal revizyon talepcisi ve @bahsedilen kullanıcılar',
    Notification.REVISION_REJECTED:      'Revizyon talebini açan kişi',
    Notification.JOB_ON_HOLD:            'İş emrindeki tüm görev sorumluları',
    Notification.JOB_RESUMED:            'İş emrindeki tüm görev sorumluları',
    # Approvals — requestor/submitter always notified of outcome
    Notification.PR_APPROVAL_REQUESTED:  'Onay aşamasındaki onaylayıcılar',
    Notification.PR_APPROVED:            'Talebi oluşturan kişi',
    Notification.PR_REJECTED:            'Talebi oluşturan kişi',
    Notification.PR_PO_CREATED:          'Talebi oluşturan kişi',
    Notification.OT_APPROVAL_REQUESTED:  'Onay aşamasındaki onaylayıcılar',
    Notification.OT_APPROVED:            'Talebi oluşturan kişi',
    Notification.OT_REJECTED:            'Talebi oluşturan kişi',
    Notification.PLAN_APPROVAL_REQUESTED:'Onay aşamasındaki onaylayıcılar',
    Notification.PLAN_APPROVED:          'Talebi oluşturan kişi',
    Notification.PLAN_REJECTED:          'Talebi oluşturan kişi',
    Notification.PLAN_DR_APPROVED:       'Talebi oluşturan kişi',
    Notification.SUB_APPROVAL_REQUESTED: 'Onay aşamasındaki onaylayıcılar',
    Notification.SUB_APPROVED:           'Hakedişi oluşturan kişi',
    Notification.SUB_REJECTED:           'Hakedişi oluşturan kişi',
    # Sales
    Notification.SALES_APPROVAL_REQUESTED: 'Onay aşamasındaki onaylayıcılar',
    Notification.SALES_APPROVED:           'Teklifi oluşturan kişi',
    Notification.SALES_REJECTED:           'Teklifi oluşturan kişi',
    Notification.SALES_CONSULTATION:       'İlgili departman müdürleri ve danışma görevine atanan kişi',
    Notification.SALES_CONVERTED:          None,
    # QC
    Notification.QC_REVIEW_SUBMITTED:    'KK ekibi üyeleri',
    Notification.QC_REVIEW_APPROVED:     'İncelemeyi gönderen kişi',
    Notification.QC_REVIEW_REJECTED:     'İncelemeyi gönderen kişi',
    Notification.NCR_CREATED:            'KK ekibi üyeleri ve görev sorumlusu',
    Notification.NCR_SUBMITTED:          'KK ekibi onaylayıcıları',
    Notification.NCR_APPROVED:           'NCR\'ı oluşturan kişi',
    Notification.NCR_REJECTED:           'NCR\'ı oluşturan kişi',
    Notification.NCR_ASSIGNED:           'NCR\'a atanan kişiler',
    # Auth
    Notification.PASSWORD_RESET:         'IT yöneticileri',
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
            'default_send_email',
            'default_send_in_app',
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
        for attr in (
            'title_template', 'body_template', 'link_template',
            'default_send_email', 'default_send_in_app',
            'teams', 'enabled',
        ):
            if attr in validated_data:
                setattr(instance, attr, validated_data[attr])
        instance.save()
        if user_ids is not None:
            from django.contrib.auth.models import User
            instance.users.set(User.objects.filter(id__in=user_ids, is_active=True))
        from notifications.service import invalidate_config_cache
        invalidate_config_cache()
        return instance
