from django.db import migrations

CODENAME = 'access_manufacturing_welding_capacity_planning'
PERM_NAME = 'Page: /manufacturing/welding/capacity-planning/'
SECTION = 'manufacturing'


def add_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')
    Position = apps.get_model('organization', 'Position')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.get_or_create(
        codename=CODENAME,
        content_type=ct,
        defaults={'name': PERM_NAME},
    )
    meta, _ = PermissionMeta.objects.update_or_create(
        codename=CODENAME,
        defaults={'name': PERM_NAME, 'section': SECTION},
    )

    # Grant page access to every position available.
    for position in Position.objects.all():
        position.permissions.add(meta)


def remove_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.filter(codename=CODENAME, content_type=ct).delete()
    # Deleting the PermissionMeta also clears the Position m2m rows.
    PermissionMeta.objects.filter(codename=CODENAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0044_add_quality_documents_permission'),
        ('organization', '0003_seed_positions_and_permissions'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(add_permission, reverse_code=remove_permission),
    ]
