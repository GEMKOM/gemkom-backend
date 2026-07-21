from django.db import migrations

SECTION = 'general'

# (codename, name)
# Page perms use the exact "Page: <route>/" format — routeIsAllowedByGrantedPages()
# on the frontend does an exact normalized match, so every route needs its own row.
PERMISSIONS = [
    ('access_general_crane_requests', 'Page: /general/crane-requests/'),
    ('access_general_crane_requests_list', 'Page: /general/crane-requests/list/'),
    ('access_general_crane_requests_pending', 'Page: /general/crane-requests/pending/'),
    ('access_general_crane_requests_prices', 'Page: /general/crane-requests/prices/'),
    ('manage_crane_prices', 'Vinç fiyat listesini düzenleyebilir'),
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

    # Deliberately NOT granted to every Position: departments that should
    # create crane requests get the page perms from the IT > Yetkiler screen.


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
        ('users', '0046_add_overtime_report_permissions'),
        ('organization', '0003_seed_positions_and_permissions'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(add_permissions, reverse_code=remove_permissions),
    ]
