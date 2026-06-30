from django.db import migrations

CODENAME = 'view_machining_performance_report'
PERM_NAME = 'Page: /manufacturing/machining/reports/performance/'


def add_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.get_or_create(
        codename=CODENAME,
        content_type=ct,
        defaults={'name': PERM_NAME},
    )
    PermissionMeta.objects.update_or_create(
        codename=CODENAME,
        defaults={'name': PERM_NAME, 'section': 'manufacturing'},
    )


def remove_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.filter(codename=CODENAME, content_type=ct).delete()
    PermissionMeta.objects.filter(codename=CODENAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0042_add_design_release_approvals_permission'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(add_permission, reverse_code=remove_permission),
    ]
