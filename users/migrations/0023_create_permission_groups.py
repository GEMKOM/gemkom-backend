from django.db import migrations


# Maps each Django Group name → list of permission codenames it should have.
GROUP_PERMISSIONS = {
    'planning_team': [
        'access_planning_write',
        'mark_delivered',
        'view_all_user_hours',
        'view_procurement_costs',
        'manage_planning_requests',
    ],
    'planning_manager': [
        'access_planning_write',
        'mark_delivered',
        'view_all_user_hours',
        'view_procurement_costs',
        'manage_planning_requests',
        'view_job_costs',
        'view_cost_pages',
    ],
    'procurement_team': [
        'access_finance',
        'access_procurement_write',
        'mark_delivered',
        'view_finance_pages',
    ],
    'finance_team': [
        'access_finance',
        'view_finance_pages',
    ],
    'accounting_team': [
        'access_finance',
        'view_finance_pages',
    ],
    'management_team': [
        'access_finance',
        'view_job_costs',
        'view_all_user_hours',
        'view_procurement_costs',
        'view_qc_costs',
        'view_shipping_costs',
        'view_cost_pages',
        'view_finance_pages',
    ],
    'machining_team': [
        'access_machining',
    ],
    'welding_team': [
        'access_welding',
    ],
    'cutting_team': [
        'access_cutting',
    ],
    'sales_team': [
        'access_sales',
    ],
    'warehouse_team': [
        'access_warehouse_write',
        'mark_delivered',
    ],
    'qualitycontrol_team': [
        'view_qc_costs',
    ],
    'logistics_team': [
        'view_shipping_costs',
    ],
    'hr_team': [
        'manage_hr',
        'view_hr_pages',
    ],
    'external_workshops_team': [
        'access_finance',
        'view_finance_pages',
    ],
}

# Maps profile.team value → group name(s) a user should be assigned to.
TEAM_TO_GROUPS = {
    'planning':          ['planning_team'],
    'procurement':       ['procurement_team'],
    'finance':           ['finance_team'],
    'accounting':        ['accounting_team'],
    'management':        ['management_team'],
    'machining':         ['machining_team'],
    'welding':           ['welding_team'],
    'cutting':           ['cutting_team'],
    'sales':             ['sales_team'],
    'warehouse':         ['warehouse_team'],
    'qualitycontrol':    ['qualitycontrol_team'],
    'logistics':         ['logistics_team'],
    'human_resouces':    ['hr_team'],
    'external_workshops': ['external_workshops_team'],
    # teams with no specific access requirements — no group needed
    'design':            [],
    'manufacturing':     [],
    'maintenance':       [],
    'rollingmill':       [],
}


CUSTOM_PERMISSIONS = [
    ('access_machining',          'Can access machining module'),
    ('access_cutting',            'Can access CNC cutting module'),
    ('access_welding',            'Can access welding module'),
    ('access_sales',              'Can access sales module'),
    ('access_finance',            'Can access finance data'),
    ('access_planning_write',     'Can create/edit planning requests'),
    ('access_warehouse_write',    'Can perform warehouse write operations'),
    ('access_procurement_write',  'Can perform procurement write operations'),
    ('mark_delivered',            'Can mark items as delivered'),
    ('manage_hr',                 'Can manage HR wage records'),
    ('view_job_costs',            'Can view job cost breakdowns'),
    ('view_all_user_hours',       "Can view all users' hours"),
    ('view_procurement_costs',    'Can view procurement cost lines'),
    ('view_qc_costs',             'Can view QC cost lines'),
    ('view_shipping_costs',       'Can view shipping cost lines'),
    ('manage_planning_requests',  'Can manage planning request lifecycle'),
    ('view_finance_pages',        'Frontend: can see finance pages'),
    ('view_hr_pages',             'Frontend: can see HR pages'),
    ('view_cost_pages',           'Frontend: can see cost breakdown pages'),
]


def create_groups_and_assign_users(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    # Ensure all custom permissions exist (mirrors the post_migrate signal,
    # but runs inside the migration so groups can reference them immediately).
    ct = ContentType.objects.get_for_model(UserProfile)
    for codename, name in CUSTOM_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': name},
        )

    # Build codename → Permission lookup.
    all_codenames = [c for perms in GROUP_PERMISSIONS.values() for c in perms]
    perm_lookup = {
        p.codename: p
        for p in Permission.objects.filter(codename__in=all_codenames)
    }

    # 1. Create groups and assign permissions.
    for group_name, codenames in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.set([
            perm_lookup[c] for c in codenames if c in perm_lookup
        ])

    # 2. Assign existing users to groups based on team / occupation.
    for profile in UserProfile.objects.select_related('user').all():
        groups_to_add = list(TEAM_TO_GROUPS.get(profile.team, []))

        # planning managers get the extra planning_manager group on top of planning_team
        if profile.team == 'planning' and profile.occupation == 'manager':
            groups_to_add.append('planning_manager')

        for group_name in groups_to_add:
            try:
                group = Group.objects.get(name=group_name)
                profile.user.groups.add(group)
            except Group.DoesNotExist:
                pass


def remove_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=GROUP_PERMISSIONS.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0022_remove_wagerate_base_hourly'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(
            create_groups_and_assign_users,
            reverse_code=remove_groups,
        ),
    ]
