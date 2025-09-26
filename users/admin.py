from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import UserProfile, WageRate

# Inline profile for User admin
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'

# Extended User admin
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]

    def team(self, instance):
        return instance.profile.team if hasattr(instance, 'profile') else '-'
    
    def is_admin(self, instance):
        return instance.profile.work_location == "office" if hasattr(instance, 'profile') else False
    is_admin.boolean = True  # show as checkmark in admin
    is_admin.short_description = 'Admin?'

    list_display = BaseUserAdmin.list_display + ('team', 'is_admin',)
    search_fields = BaseUserAdmin.search_fields + ('profile__team',)
    list_filter = BaseUserAdmin.list_filter + ('profile__team',)

@admin.register(WageRate)
class WageRateAdmin(admin.ModelAdmin):
    list_display = ("user", "effective_from", "base_hourly", "currency")
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

# Unregister and re-register with custom admin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
