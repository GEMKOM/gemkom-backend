from django.db import migrations

SECTION = 'general'

# (codename, "Page: <route>/")
PERMISSIONS = [
    ('access_general_overtime_cost_report', 'Page: /general/overtime/cost-report/'),
    # The machining report page has existed on the frontend since it was built
    # but was never registered here, so routeIsAllowedByGrantedPages() could
    # never match it and only superusers ever saw it. Registering it alongside
    # the new page fixes that.
    ('access_general_overtime_machining_report', 'Page: /general/overtime/machining-report/'),
]


def add_permissions(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')

    ct = ContentType.objects.get_for_model(UserProfile)
    for codename, perm_name in PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': perm_name},
        )
        PermissionMeta.objects.update_or_create(
            codename=codename,
            defaults={'name': perm_name, 'section': SECTION},
        )

    # Deliberately NOT granted to every Position (unlike migration 0045):
    # the cost report exposes wage-derived figures, so access is assigned
    # per-position from the IT > Yetkiler screen instead.


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')

    ct = ContentType.objects.get_for_model(UserProfile)
    codenames = [c for c, _ in PERMISSIONS]
    Permission.objects.filter(codename__in=codenames, content_type=ct).delete()
    # Deleting the PermissionMeta also clears the Position m2m rows.
    PermissionMeta.objects.filter(codename__in=codenames).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0045_add_welding_capacity_planning_permission'),
        ('organization', '0003_seed_positions_and_permissions'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(add_permissions, reverse_code=remove_permissions),
    ]
