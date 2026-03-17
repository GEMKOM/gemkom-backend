from django.db import migrations


def create_machining_admin_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.get_or_create(
        codename='machining_admin',
        content_type=ct,
        defaults={'name': 'Can access machining reports, planning, and manual entries'},
    )


def remove_machining_admin_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.filter(codename='machining_admin', content_type=ct).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0025_portal_access_permissions'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(
            create_machining_admin_permission,
            reverse_code=remove_machining_admin_permission,
        ),
    ]
