from django.db import migrations

CODENAME = 'access_design_release_approvals'
PERM_NAME = 'Page: /design/release-approvals/'


def grant_to_design_positions(apps, schema_editor):
    """Grant permission to all active positions tagged with department_code='design'."""
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

    perm_meta, _ = PermissionMeta.objects.update_or_create(
        codename=CODENAME,
        defaults={'name': PERM_NAME, 'section': 'design'},
    )

    design_positions = Position.objects.filter(
        department_code='design',
        is_active=True,
    )
    for pos in design_positions:
        pos.permissions.add(perm_meta)


def revoke_from_design_positions(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')
    Position = apps.get_model('organization', 'Position')

    ct = ContentType.objects.get_for_model(UserProfile)
    perm_meta = PermissionMeta.objects.filter(codename=CODENAME).first()
    if perm_meta:
        for pos in Position.objects.filter(department_code='design', is_active=True):
            pos.permissions.remove(perm_meta)
        perm_meta.delete()

    Permission.objects.filter(codename=CODENAME, content_type=ct).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0041_add_personel_fields_to_userprofile'),
        ('organization', '0007_remove_usergroup_organization_usergroup_slug_unique_and_more'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(
            grant_to_design_positions,
            reverse_code=revoke_from_design_positions,
        ),
    ]
