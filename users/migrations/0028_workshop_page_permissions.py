from django.db import migrations

REMOVED_CODENAMES = [
    'access_workshop_cnc_cutting_tasks',
    'access_workshop_department_requests',
    'access_workshop_department_requests_create',
    'access_workshop_machining_tasks',
    'access_manufacturing_maintenance_create',
    'access_manufacturing_maintenance_list',
]

NEW_PERMISSIONS = [
    ('access_cnc_cutting',                      'Page: /cnc_cutting/'),
    ('access_cnc_cutting_tasks',                'Page: /cnc_cutting/tasks/'),
    ('access_department_requests',              'Page: /department-requests/'),
    ('access_department_requests_create',       'Page: /department-requests/create/'),
    ('access_machining',                        'Page: /machining/'),
    ('access_machining_tasks',                  'Page: /machining/tasks/'),
    ('access_maintenance',                      'Page: /maintenance/'),
    ('access_maintenance_create',               'Page: /maintenance/create/'),
    ('access_maintenance_list',                 'Page: /maintenance/list/'),
    ('access_warehouse',                        'Page: /warehouse/'),
    ('access_warehouse_inventory_allocation',   'Page: /warehouse/inventory-allocation/'),
    ('access_warehouse_material_tracking',      'Page: /warehouse/material-tracking/'),
    ('access_warehouse_weight_reduction',       'Page: /warehouse/weight-reduction/'),
]


def add_permissions(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.filter(codename__in=REMOVED_CODENAMES, content_type=ct).delete()
    for codename, name in NEW_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': name},
        )


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    ct = ContentType.objects.get_for_model(UserProfile)
    codenames = [c for c, _ in NEW_PERMISSIONS]
    Permission.objects.filter(codename__in=codenames, content_type=ct).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0027_rebuild_permissions'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(add_permissions, reverse_code=remove_permissions),
    ]
