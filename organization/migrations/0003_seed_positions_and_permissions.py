"""
Seed the Position tree and assign permissions to positions.

Permission sets are derived directly from the GROUP_PERMISSIONS dict in
migration users/0023_create_permission_groups so that existing users lose
no permissions after the org backfill migration runs.

Tree structure (matches the actual GEMKOM org chart):

  Yönetim Kurulu          L1   (no dept)
  └── Genel Müdür         L2   (no dept)
        ├── Fabrika Müdürü              L3  manufacturing
        │     ├── İmalat Müdürü         L4  manufacturing
        │     ├── Planlama ve Depo Müdürü L4 planning
        │     ├── Kalite Kontrol Müdürü L4  qualitycontrol
        │     └── Lojistik Şefi        L4  logistics
        ├── Satış/Paz./Proje Müdürü    L3  sales
        │     ├── Satış Şefi           L4  sales
        │     └── Proje Sorumlusu      L5  sales
        ├── Finans ve Mali İşler Müdürü L3  finance
        │     ├── Muhasebe Müdürü      L4  accounting
        │     ├── Satınalma Şefi       L4  procurement
        │     └── Dış Ticaret Sorumlusu L5 finance
        ├── ArGe ve Tasarım Müdürü     L3  design
        │     └── Haddehane Tasarım Şefi L4 rollingmill
        ├── İK ve İdari İşler Müdürü   L3  human_resources
        └── Haddehane Grup Müdürü      L3  rollingmill
              ├── İmalat ve Montaj Şefi L4  rollingmill
              ├── Elektrik Otomasyon Sorumlusu L5 rollingmill
              └── Proje Sorumlusu      L5  rollingmill

Additionally, generic staff positions (L6) are created for each department
so that every existing user can be mapped to a position during the backfill.
"""
from django.db import migrations


# ---------------------------------------------------------------------------
# Permission assignment by department + position level.
# Sourced from GROUP_PERMISSIONS in users/0023_create_permission_groups.
# ---------------------------------------------------------------------------

# Permissions that ALL office-facing positions get (for portal access gate).
OFFICE_ACCESS_DEPTS = {
    'planning', 'procurement', 'finance', 'accounting', 'management',
    'sales', 'qualitycontrol', 'logistics', 'human_resources', 'design',
    'external_workshops',
}

WORKSHOP_ACCESS_DEPTS = {
    'machining', 'welding', 'cutting', 'warehouse',
    'manufacturing', 'maintenance', 'rollingmill',
}

# codenames granted to positions in these departments at ANY level
DEPT_BASE_PERMS = {
    'planning':           ['access_planning_write', 'mark_delivered', 'view_all_user_hours', 'view_procurement_costs', 'manage_planning_requests'],
    'planning_manager':   ['access_planning_write', 'mark_delivered', 'view_all_user_hours', 'view_procurement_costs', 'manage_planning_requests', 'view_job_costs', 'view_cost_pages'],
    'procurement':        ['access_finance', 'access_procurement_write', 'mark_delivered', 'view_finance_pages'],
    'finance':            ['access_finance', 'view_finance_pages'],
    'accounting':         ['access_finance', 'view_finance_pages'],
    'management':         ['access_finance', 'view_job_costs', 'view_all_user_hours', 'view_procurement_costs', 'view_qc_costs', 'view_shipping_costs', 'view_cost_pages', 'view_finance_pages'],
    'machining':          ['access_machining'],
    'welding':            ['access_welding'],
    'cutting':            ['access_cutting'],
    'sales':              ['access_sales'],
    'warehouse':          ['access_warehouse_write', 'mark_delivered'],
    'qualitycontrol':     ['view_qc_costs'],
    'logistics':          ['view_shipping_costs'],
    'human_resources':    ['manage_hr', 'view_hr_pages'],
    'external_workshops': ['access_finance', 'view_finance_pages'],
}

# Manager-level (L3 and above) in planning also get these extra codenames
PLANNING_MANAGER_EXTRA = ['view_job_costs', 'view_cost_pages']


def _perms_for(dept_code: str, level: int) -> list[str]:
    """Return codenames for a position based on department and level."""
    codenames = set()

    # Portal access
    if dept_code in OFFICE_ACCESS_DEPTS:
        codenames.add('office_access')
    if dept_code in WORKSHOP_ACCESS_DEPTS:
        codenames.add('workshop_access')

    # Department base perms
    base = DEPT_BASE_PERMS.get(dept_code, [])
    codenames.update(base)

    # Planning managers get extra perms at L3+
    if dept_code == 'planning' and level <= 3:
        codenames.update(PLANNING_MANAGER_EXTRA)

    # Management dept always gets everything at all levels
    if dept_code == 'management':
        codenames.update(DEPT_BASE_PERMS['management'])

    return sorted(codenames)


def seed(apps, schema_editor):
    Department = apps.get_model('organization', 'Department')
    Position = apps.get_model('organization', 'Position')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')

    def get_dept(code):
        return Department.objects.filter(code=code).first()

    def make(title, level, parent, dept_code, extra_perms=None):
        dept = get_dept(dept_code) if dept_code else None
        pos = Position.objects.create(
            title=title,
            level=level,
            parent=parent,
            department=dept,
            is_active=True,
        )
        codenames = _perms_for(dept_code or '', level)
        if extra_perms:
            codenames = list(set(codenames) | set(extra_perms))
        perms = PermissionMeta.objects.filter(codename__in=codenames)
        pos.permissions.set(perms)
        return pos

    # ---- L1: Board ----
    board = make('Yönetim Kurulu', 1, None, 'management')

    # ---- L2: General Manager ----
    gm = make('Genel Müdür', 2, board, 'management')

    # ---- L3: Department Directors ----
    fabrika  = make('Fabrika Müdürü',                    3, gm, 'manufacturing')
    satis_d  = make('Satış, Pazarlama ve Proje Müdürü',  3, gm, 'sales')
    finans_d = make('Finans ve Mali İşler Müdürü',       3, gm, 'finance')
    arge_d   = make('ArGe ve Tasarım Müdürü',            3, gm, 'design')
    ik_d     = make('İnsan Kaynakları ve İdari İşler Müdürü', 3, gm, 'human_resources')
    hadde_d  = make('Haddehane Grup Müdürü',             3, gm, 'rollingmill')

    # ---- L4: Managers / Chiefs under Fabrika ----
    make('İmalat Müdürü',           4, fabrika, 'manufacturing')
    make('Planlama ve Depo Müdürü', 4, fabrika, 'planning')
    make('Kalite Kontrol Müdürü',   4, fabrika, 'qualitycontrol')
    make('Lojistik Şefi',           4, fabrika, 'logistics')

    # ---- L4/L5: Under Satış ----
    make('Satış Şefi',       4, satis_d, 'sales')
    make('Proje Sorumlusu',  5, satis_d, 'sales')

    # ---- L4/L5: Under Finans ----
    make('Muhasebe Müdürü',         4, finans_d, 'accounting')
    make('Satınalma Şefi',          4, finans_d, 'procurement')
    make('Dış Ticaret Sorumlusu',   5, finans_d, 'finance')

    # ---- L4: Under ArGe ----
    make('Haddehane Tasarım Şefi',  4, arge_d, 'rollingmill')

    # ---- L4/L5: Under Haddehane ----
    make('İmalat ve Montaj Şefi',          4, hadde_d, 'rollingmill')
    make('Elektrik Otomasyon Sorumlusu',   5, hadde_d, 'rollingmill')
    make('Proje Sorumlusu (Haddehane)',    5, hadde_d, 'rollingmill')

    # ---- Generic staff positions per department (L6) ----
    # These are catch-all positions for standard employees in each department.
    # The backfill migration assigns users here when no specific position matches.
    staff_depts = [
        ('machining',          'Operatör'),
        ('design',             'Dizayn Uzmanı'),
        ('logistics',          'Lojistik Personeli'),
        ('procurement',        'Satın Alma Personeli'),
        ('welding',            'Kaynakçı'),
        ('planning',           'Planlama Personeli'),
        ('manufacturing',      'İmalat Personeli'),
        ('maintenance',        'Bakım Personeli'),
        ('rollingmill',        'Haddehane Personeli'),
        ('qualitycontrol',     'Kalite Kontrol Personeli'),
        ('cutting',            'CNC Operatörü'),
        ('warehouse',          'Ambar Personeli'),
        ('finance',            'Finans Personeli'),
        ('management',         'Yönetim Personeli'),
        ('external_workshops', 'Dış Atölye Personeli'),
        ('human_resources',    'İK Personeli'),
        ('sales',              'Satış Personeli'),
        ('accounting',         'Muhasebe Personeli'),
    ]
    for dept_code, title in staff_depts:
        make(title, 6, None, dept_code)


def unseed(apps, schema_editor):
    Position = apps.get_model('organization', 'Position')
    Position.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0002_seed_departments'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
