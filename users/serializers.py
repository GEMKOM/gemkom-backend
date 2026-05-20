from django.contrib.auth.models import User
from rest_framework import serializers
from .models import UserProfile, WageRate
from organization.models import Position, UserGroup


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class SimpleUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class PublicUserSerializer(serializers.ModelSerializer):
    department_code = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'department_code']

    def get_department_code(self, obj):
        try:
            return obj.profile.position.department_code or None
        except Exception:
            return None


class UserPasswordResetSerializer(serializers.ModelSerializer):
    reset_password_request = serializers.BooleanField(source='profile.reset_password_request')
    must_reset_password    = serializers.BooleanField(source='profile.must_reset_password')
    department_code        = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'is_superuser',
            'department_code', 'reset_password_request', 'must_reset_password',
        ]

    def get_department_code(self, obj):
        try:
            return obj.profile.position.department_code or None
        except Exception:
            return None


class UserListSerializer(serializers.ModelSerializer):
    must_reset_password  = serializers.BooleanField(source='profile.must_reset_password')
    position_id          = serializers.IntegerField(source='profile.position_id', read_only=True)
    position_title       = serializers.SerializerMethodField()
    position_level       = serializers.SerializerMethodField()
    department_code      = serializers.SerializerMethodField()
    birth_date           = serializers.DateField(source='profile.birth_date', read_only=True)
    hire_date            = serializers.DateField(source='profile.hire_date', read_only=True)
    personel_kodu        = serializers.CharField(source='profile.personel_kodu', read_only=True)
    tc_kimlik_no         = serializers.CharField(source='profile.tc_kimlik_no', read_only=True)
    gender               = serializers.CharField(source='profile.gender', read_only=True)
    sigorta_yuzde_grubu  = serializers.CharField(source='profile.sigorta_yuzde_grubu', read_only=True)
    user_groups          = serializers.SerializerMethodField()
    user_group_ids       = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'is_superuser',
            'position_id', 'position_title', 'position_level',
            'department_code',
            'must_reset_password', 'is_active',
            'birth_date', 'hire_date',
            'personel_kodu', 'tc_kimlik_no', 'gender', 'sigorta_yuzde_grubu',
            'user_groups', 'user_group_ids',
        ]

    def get_position_title(self, obj):
        try:
            return obj.profile.position.title if obj.profile.position_id else None
        except Exception:
            return None

    def get_position_level(self, obj):
        try:
            return obj.profile.position.level if obj.profile.position_id else None
        except Exception:
            return None

    def get_department_code(self, obj):
        try:
            return obj.profile.position.department_code or None
        except Exception:
            return None

    def _user_groups_data(self, obj):
        cache_key = f'_ug_{obj.pk}'
        if not hasattr(self, cache_key):
            try:
                position_id = obj.profile.position_id
                result = list(
                    UserGroup.objects.filter(
                        is_active=True,
                        positions__id=position_id,
                    ).values('id', 'slug')
                ) if position_id else []
            except Exception:
                result = []
            setattr(self, cache_key, result)
        return getattr(self, cache_key)

    def get_user_groups(self, obj):
        return [g['slug'] for g in self._user_groups_data(obj)]

    def get_user_group_ids(self, obj):
        return [g['id'] for g in self._user_groups_data(obj)]


class UserCreateSerializer(serializers.ModelSerializer):
    position = serializers.PrimaryKeyRelatedField(
        queryset=Position.objects.filter(is_active=True),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'position']

    def create(self, validated_data):
        position = validated_data.pop('position', None)

        user = User.objects.create(
            username=validated_data.get('username'),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            email=validated_data.get('email', ''),
        )
        user.set_password("gemkom2025.")
        user.save()

        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                'must_reset_password': True,
                'position': position,
            },
        )

        return user


class PasswordResetSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        return value

    def save(self, user):
        user.set_password(self.validated_data['new_password'])
        user.save()
        profile = user.profile
        profile.must_reset_password = False
        profile.save()


class CurrentUserUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    must_reset_password = serializers.BooleanField(source='profile.must_reset_password', required=False)
    birth_date          = serializers.DateField(source='profile.birth_date', required=False, allow_null=True)
    hire_date           = serializers.DateField(source='profile.hire_date', required=False, allow_null=True)
    position = serializers.PrimaryKeyRelatedField(
        source='profile.position',
        queryset=Position.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'email',
            'position', 'must_reset_password', 'is_active',
            'birth_date', 'hire_date',
        ]

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        profile = instance.profile
        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save(update_fields=list(profile_data.keys()) if profile_data else None)

        return instance


class UserMiniSerializer(serializers.ModelSerializer):
    position_id     = serializers.IntegerField(source='profile.position_id', read_only=True)
    position_title  = serializers.SerializerMethodField()
    position_level  = serializers.SerializerMethodField()
    department_code = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name",
            "position_id", "position_title", "position_level",
            "department_code",
        ]

    def get_position_title(self, obj):
        try:
            return obj.profile.position.title if obj.profile.position_id else None
        except Exception:
            return None

    def get_position_level(self, obj):
        try:
            return obj.profile.position.level if obj.profile.position_id else None
        except Exception:
            return None

    def get_department_code(self, obj):
        try:
            return obj.profile.position.department_code or None
        except Exception:
            return None


class UserWageOverviewSerializer(serializers.ModelSerializer):
    user_info   = UserMiniSerializer(source="*", read_only=True)
    has_wage    = serializers.BooleanField(read_only=True)
    current_wage = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "user_info", "has_wage", "current_wage"]

    def get_current_wage(self, obj):
        if getattr(obj, "current_wage_id", None) is None:
            return None
        return {
            "id": obj.current_wage_id,
            "effective_from": obj.current_effective_from,
            "base_monthly": obj.current_base_monthly,
            "after_hours_multiplier": obj.current_after_hours_multiplier,
            "sunday_multiplier": obj.current_sunday_multiplier,
        }


class WageRateSerializer(serializers.ModelSerializer):
    user      = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    user_info = UserMiniSerializer(source="user", read_only=True)

    class Meta:
        model = WageRate
        fields = [
            "id", "user", "user_info",
            "effective_from", "currency",
            "base_monthly", "after_hours_multiplier", "sunday_multiplier",
            "note", "created_at", "created_by", "updated_at", "updated_by",
        ]
        read_only_fields = ["created_at", "created_by", "updated_at", "updated_by"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        validated_data["updated_by"] = self.context["request"].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(instance, validated_data)


class WageRateSlimSerializer(WageRateSerializer):
    class Meta(WageRateSerializer.Meta):
        fields = [f for f in WageRateSerializer.Meta.fields if f != "user_info"]
