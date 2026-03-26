from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin, GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from .models import UserProfile, WageRate, UserPermissionOverride, PermissionMeta
from .constants import GROUP_DISPLAY_NAMES

# Inline profile for User admin
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'

# Extended User admin
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]

    def portals(self, instance):
        perms = set(
            instance.user_permissions.values_list('codename', flat=True)
        ) | set(
            p for g in instance.groups.prefetch_related('permissions').all()
            for p in g.permissions.values_list('codename', flat=True)
        )
        result = []
        if instance.is_superuser or 'office_access' in perms:
            result.append('office')
        if instance.is_superuser or 'workshop_access' in perms:
            result.append('workshop')
        return ', '.join(result) if result else '-'
    portals.short_description = 'Portals'

    list_display = BaseUserAdmin.list_display + ('portals',)
    search_fields = BaseUserAdmin.search_fields + ('groups__name',)
    list_filter = BaseUserAdmin.list_filter + ('groups',)

@admin.register(WageRate)
class WageRateAdmin(admin.ModelAdmin):
    list_display = ("user", "effective_from", "base_monthly", "currency")
    ordering = ("user__username", "-effective_from")

    def has_view_permission(self, request, obj=None):
        u = request.user
        return u.is_superuser or u.groups.filter(name__in=["HR", "Management"]).exists() or u.has_perm("payroll.view_wage")

    def has_change_permission(self, request, obj=None):
        u = request.user
        return u.is_superuser or u.groups.filter(name__in=["HR"]).exists() or u.has_perm("payroll.change_wage")

    def has_add_permission(self, request):
        u = request.user
        return u.is_superuser or u.groups.filter(name__in=["HR"]).exists() or u.has_perm("payroll.add_wage")

    def has_delete_permission(self, request, obj=None):
        u = request.user
        return u.is_superuser or u.groups.filter(name__in=["HR"]).exists() or u.has_perm("payroll.delete_wage")

@admin.register(UserPermissionOverride)
class UserPermissionOverrideAdmin(admin.ModelAdmin):
    list_display  = ('user', 'codename', 'granted', 'reason', 'created_by', 'created_at')
    list_filter   = ('granted', 'codename')
    search_fields = ('user__username', 'codename', 'reason')
    raw_id_fields = ('user', 'created_by')
    ordering      = ('user__username', 'codename')

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class GroupMemberInline(admin.TabularInline):
    model = User.groups.through
    extra = 0
    verbose_name = 'Member'
    verbose_name_plural = 'Members'
    raw_id_fields = ('user',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user__profile')

    def has_add_permission(self, request, obj=None):
        return True

    def has_change_permission(self, request, obj=None):
        return False



class GroupAdmin(BaseGroupAdmin):
    list_display = ('display_name', 'name', 'member_count')
    inlines = [GroupMemberInline]

    def display_name(self, obj):
        return GROUP_DISPLAY_NAMES.get(obj.name, obj.name)
    display_name.short_description = 'Display Name'
    display_name.admin_order_field = 'name'

    def member_count(self, obj):
        return obj.user_set.count()
    member_count.short_description = 'Members'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('user_set')


@admin.register(PermissionMeta)
class PermissionMetaAdmin(admin.ModelAdmin):
    """
    Single place to manage all custom permissions.
    Saving here automatically creates/updates the matching auth.Permission row.
    """
    list_display  = ('codename', 'name', 'section')
    list_filter   = ('section',)
    search_fields = ('codename', 'name')
    ordering      = ('section', 'codename')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Keep auth.Permission in sync
        ct = ContentType.objects.get_for_model(UserProfile)
        Permission.objects.update_or_create(
            codename=obj.codename,
            content_type=ct,
            defaults={'name': obj.name},
        )

    def delete_model(self, request, obj):
        ct = ContentType.objects.get_for_model(UserProfile)
        Permission.objects.filter(codename=obj.codename, content_type=ct).delete()
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        ct = ContentType.objects.get_for_model(UserProfile)
        codenames = list(queryset.values_list('codename', flat=True))
        Permission.objects.filter(codename__in=codenames, content_type=ct).delete()
        super().delete_queryset(request, queryset)


# Unregister and re-register with custom admin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)
