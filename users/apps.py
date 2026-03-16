from django.apps import AppConfig

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
    ('office_access',             'Can log in to the office portal (ofis.gemcore.com.tr)'),
    ('workshop_access',           'Can log in to the workshop portal (saha.gemcore.com.tr)'),
]


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'

    def ready(self):
        import users.signals
        from django.db.models.signals import post_migrate
        post_migrate.connect(_create_custom_permissions, sender=self)


def _create_custom_permissions(sender, **kwargs):
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from users.models import UserProfile
    except Exception:
        return

    ct = ContentType.objects.get_for_model(UserProfile)
    for codename, name in CUSTOM_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': name},
        )
