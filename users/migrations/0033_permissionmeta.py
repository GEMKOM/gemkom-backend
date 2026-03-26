from django.db import migrations, models


SECTION_MAP = {
    'workshop': [
        'access_cnc_cutting', 'access_cnc_cutting_tasks',
        'access_department_requests', 'access_department_requests_create',
        'access_machining', 'access_machining_tasks',
        'access_maintenance', 'access_maintenance_create', 'access_maintenance_list',
        'access_warehouse', 'access_warehouse_inventory_allocation',
        'access_warehouse_material_tracking', 'access_warehouse_weight_reduction',
    ],
    'manufacturing': [
        'access_manufacturing', 'access_manufacturing_material_tracking',
        'access_manufacturing_projects', 'access_manufacturing_reports',
        'access_manufacturing_reports_combined_job_costs',
        'access_manufacturing_cnc_cutting', 'access_manufacturing_cnc_cutting_capacity',
        'access_manufacturing_cnc_cutting_capacity_planning',
        'access_manufacturing_cnc_cutting_cuts', 'access_manufacturing_cnc_cutting_dashboard',
        'access_manufacturing_cnc_cutting_remnants', 'access_manufacturing_cnc_cutting_reports',
        'access_manufacturing_cnc_cutting_reports_finished_timers',
        'access_manufacturing_cnc_cutting_reports_parts_search',
        'access_manufacturing_machining', 'access_manufacturing_machining_capacity',
        'access_manufacturing_machining_capacity_planning',
        'access_manufacturing_machining_create_task',
        'access_manufacturing_machining_dashboard', 'access_manufacturing_machining_reports',
        'access_manufacturing_machining_reports_cost_analysis',
        'access_manufacturing_machining_reports_daily_efficiency',
        'access_manufacturing_machining_reports_daily_report',
        'access_manufacturing_machining_reports_finished_timers',
        'access_manufacturing_machining_reports_history',
        'access_manufacturing_machining_reports_production_plan',
        'access_manufacturing_machining_reports_sum_report',
        'access_manufacturing_machining_tasks',
        'access_manufacturing_machining_tasks_create',
        'access_manufacturing_machining_tasks_list',
        'access_manufacturing_maintenance', 'access_manufacturing_maintenance_dashboard',
        'access_manufacturing_maintenance_fault_requests',
        'access_manufacturing_maintenance_reports',
        'access_manufacturing_maintenance_reports_faults',
        'access_manufacturing_subcontracting',
        'access_manufacturing_subcontracting_overview',
        'access_manufacturing_subcontracting_statements',
        'access_manufacturing_subcontracting_subcontractors',
        'access_manufacturing_welding', 'access_manufacturing_welding_reports',
        'access_manufacturing_welding_reports_cost_analysis',
        'access_manufacturing_welding_reports_user_work_hours',
        'access_manufacturing_welding_time_entries',
    ],
    'design': [
        'access_design', 'access_design_projects', 'access_design_revision_requests',
    ],
    'finance': [
        'access_finance', 'access_finance_purchase_orders', 'access_finance_reports',
        'access_finance_reports_executive_overview', 'access_finance_reports_projects',
    ],
    'general': [
        'access_general', 'access_general_department_requests',
        'access_general_department_requests_list',
        'access_general_department_requests_pending',
        'access_general_machines', 'access_general_overtime',
        'access_general_overtime_pending', 'access_general_overtime_registry',
        'access_general_overtime_users', 'access_general_users',
    ],
    'human_resources': [
        'access_human_resources', 'access_human_resources_wages',
    ],
    'it': [
        'access_it', 'access_it_inventory', 'access_it_notifications',
        'access_it_password_resets', 'access_it_permissions',
    ],
    'logistics': [
        'access_logistics', 'access_logistics_cost_lines', 'access_logistics_projects',
    ],
    'management': [
        'access_management', 'access_management_dashboard',
    ],
    'planning': [
        'access_planning', 'access_planning_department_requests',
        'access_planning_inventory', 'access_planning_inventory_cards',
        'access_planning_procurement_lines', 'access_planning_projects',
        'access_planning_task_templates',
    ],
    'procurement': [
        'access_procurement', 'access_procurement_projects',
        'access_procurement_purchase_requests',
        'access_procurement_purchase_requests_create',
        'access_procurement_purchase_requests_pending',
        'access_procurement_purchase_requests_registry',
        'access_procurement_reports', 'access_procurement_reports_items',
        'access_procurement_reports_staff', 'access_procurement_reports_suppliers',
        'access_procurement_suppliers', 'access_procurement_suppliers_list',
        'access_procurement_suppliers_payment_terms',
    ],
    'projects': [
        'access_projects', 'access_projects_cost_table', 'access_projects_tracking',
    ],
    'quality_control': [
        'access_quality_control', 'access_quality_control_cost_lines',
        'access_quality_control_ncrs', 'access_quality_control_qc_reviews',
    ],
    'sales': [
        'access_sales', 'access_sales_catalog', 'access_sales_cost_table',
        'access_sales_customers', 'access_sales_offers',
    ],
}

# Build reverse map: codename → section
_CODENAME_TO_SECTION = {
    codename: section
    for section, codenames in SECTION_MAP.items()
    for codename in codenames
}


def seed_permission_meta(apps, schema_editor):
    PermissionMeta = apps.get_model('users', 'PermissionMeta')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    try:
        ct = ContentType.objects.get_for_model(UserProfile)
    except Exception:
        return

    rows = list(
        Permission.objects
        .filter(content_type=ct)
        .values_list('codename', 'name')
    )
    for codename, name in rows:
        PermissionMeta.objects.get_or_create(
            codename=codename,
            defaults={
                'name': name,
                'section': _CODENAME_TO_SECTION.get(codename),
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0032_remove_userprofile_team'),
    ]

    operations = [
        migrations.CreateModel(
            name='PermissionMeta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codename', models.CharField(max_length=100, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('section', models.CharField(
                    max_length=50, null=True, blank=True,
                    choices=[
                        ('workshop', 'Workshop'), ('manufacturing', 'Manufacturing'),
                        ('design', 'Design'), ('finance', 'Finance'),
                        ('general', 'General'), ('human_resources', 'Human Resources'),
                        ('it', 'IT'), ('logistics', 'Logistics'),
                        ('management', 'Management'), ('planning', 'Planning'),
                        ('procurement', 'Procurement'), ('projects', 'Projects'),
                        ('quality_control', 'Quality Control'), ('sales', 'Sales'),
                    ],
                )),
            ],
            options={
                'ordering': ['codename'],
                'verbose_name': 'Permission',
                'verbose_name_plural': 'Permissions',
            },
        ),
        migrations.RunPython(seed_permission_meta, migrations.RunPython.noop),
    ]
