from django.db import migrations


def add_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.get_or_create(
        codename='access_manufacturing_maintenance_dashboard',
        content_type=ct,
        defaults={'name': 'Page: /manufacturing/maintenance/dashboard/'},
    )


def remove_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.filter(
        codename='access_manufacturing_maintenance_dashboard',
        content_type=ct,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0030_add_maintenance_external_workshops_groups'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(add_permission, reverse_code=remove_permission),
    ]
