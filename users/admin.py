from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import UserProfile

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
        return instance.profile.location_type == "office" if hasattr(instance, 'profile') else False
    is_admin.boolean = True  # show as checkmark in admin
    is_admin.short_description = 'Admin?'

    list_display = BaseUserAdmin.list_display + ('team', 'is_admin',)
    search_fields = BaseUserAdmin.search_fields + ('profile__team',)
    list_filter = BaseUserAdmin.list_filter + ('profile__team',)

# Unregister and re-register with custom admin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
