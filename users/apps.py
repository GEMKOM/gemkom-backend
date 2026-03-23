from django.apps import AppConfig

CUSTOM_PERMISSIONS = [
    # --- Kept functional permissions ---
    ('manage_hr',        'Can manage HR wage records'),
    ('view_job_costs',   'Can view job cost breakdowns'),
    ('view_cost_pages',  'Frontend: can see cost breakdown pages'),
    ('office_access',    'Can log in to the office portal (ofis.gemcore.com.tr)'),
    ('workshop_access',  'Can log in to the workshop portal (saha.gemcore.com.tr)'),
    ('machining_admin',  'Can access machining reports, planning, and manual entries'),

    # --- Page-level permissions (one per frontend route) ---
    # Design
    ('access_design',                        'Page: /design/'),
    ('access_design_projects',               'Page: /design/projects/'),
    ('access_design_revision_requests',      'Page: /design/revision-requests/'),

    # Finance
    ('access_finance',                               'Page: /finance/'),
    ('access_finance_purchase_orders',               'Page: /finance/purchase-orders/'),
    ('access_finance_reports',                       'Page: /finance/reports/'),
    ('access_finance_reports_executive_overview',    'Page: /finance/reports/executive-overview/'),
    ('access_finance_reports_projects',              'Page: /finance/reports/projects/'),

    # General
    ('access_general',                           'Page: /general/'),
    ('access_general_department_requests',       'Page: /general/department-requests/'),
    ('access_general_department_requests_list',  'Page: /general/department-requests/list/'),
    ('access_general_department_requests_pending', 'Page: /general/department-requests/pending/'),
    ('access_general_machines',                  'Page: /general/machines/'),
    ('access_general_overtime',                  'Page: /general/overtime/'),
    ('access_general_overtime_pending',          'Page: /general/overtime/pending/'),
    ('access_general_overtime_registry',         'Page: /general/overtime/registry/'),
    ('access_general_overtime_users',            'Page: /general/overtime/users/'),
    ('access_general_users',                     'Page: /general/users/'),

    # Human Resources
    ('access_human_resources',       'Page: /human_resources/'),
    ('access_human_resources_wages', 'Page: /human_resources/wages/'),

    # IT
    ('access_it',                'Page: /it/'),
    ('access_it_inventory',      'Page: /it/inventory/'),
    ('access_it_notifications',  'Page: /it/notifications/'),
    ('access_it_password_resets','Page: /it/password-resets/'),
    ('access_it_permissions',    'Page: /it/permissions/'),

    # Logistics
    ('access_logistics',            'Page: /logistics/'),
    ('access_logistics_cost_lines', 'Page: /logistics/cost-lines/'),
    ('access_logistics_projects',   'Page: /logistics/projects/'),

    # Management
    ('access_management',           'Page: /management/'),
    ('access_management_dashboard', 'Page: /management/dashboard/'),

    # Workshop portal standalone pages
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

    # Manufacturing — CNC Cutting
    ('access_manufacturing_cnc_cutting',                    'Page: /manufacturing/cnc-cutting/'),
    ('access_manufacturing_cnc_cutting_capacity',           'Page: /manufacturing/cnc-cutting/capacity/'),
    ('access_manufacturing_cnc_cutting_capacity_planning',  'Page: /manufacturing/cnc-cutting/capacity/planning/'),
    ('access_manufacturing_cnc_cutting_cuts',               'Page: /manufacturing/cnc-cutting/cuts/'),
    ('access_manufacturing_cnc_cutting_dashboard',          'Page: /manufacturing/cnc-cutting/dashboard/'),
    ('access_manufacturing_cnc_cutting_remnants',           'Page: /manufacturing/cnc-cutting/remnants/'),
    ('access_manufacturing_cnc_cutting_reports',                    'Page: /manufacturing/cnc-cutting/reports/'),
    ('access_manufacturing_cnc_cutting_reports_finished_timers',    'Page: /manufacturing/cnc-cutting/reports/finished-timers/'),
    ('access_manufacturing_cnc_cutting_reports_parts_search',       'Page: /manufacturing/cnc-cutting/reports/parts-search/'),

    # Manufacturing — Machining
    ('access_manufacturing_machining',                          'Page: /manufacturing/machining/'),
    ('access_manufacturing_machining_capacity',                 'Page: /manufacturing/machining/capacity/'),
    ('access_manufacturing_machining_capacity_planning',        'Page: /manufacturing/machining/capacity/planning/'),
    ('access_manufacturing_machining_create_task',              'Page: /manufacturing/machining/create-task/'),
    ('access_manufacturing_machining_dashboard',                'Page: /manufacturing/machining/dashboard/'),
    ('access_manufacturing_machining_reports',                  'Page: /manufacturing/machining/reports/'),
    ('access_manufacturing_machining_reports_cost_analysis',    'Page: /manufacturing/machining/reports/cost-analysis/'),
    ('access_manufacturing_machining_reports_daily_efficiency', 'Page: /manufacturing/machining/reports/daily-efficiency/'),
    ('access_manufacturing_machining_reports_daily_report',     'Page: /manufacturing/machining/reports/daily-report/'),
    ('access_manufacturing_machining_reports_finished_timers',  'Page: /manufacturing/machining/reports/finished-timers/'),
    ('access_manufacturing_machining_reports_history',          'Page: /manufacturing/machining/reports/history/'),
    ('access_manufacturing_machining_reports_production_plan',  'Page: /manufacturing/machining/reports/production-plan/'),
    ('access_manufacturing_machining_reports_sum_report',       'Page: /manufacturing/machining/reports/sum-report/'),
    ('access_manufacturing_machining_tasks',                    'Page: /manufacturing/machining/tasks/'),
    ('access_manufacturing_machining_tasks_create',             'Page: /manufacturing/machining/tasks/create/'),
    ('access_manufacturing_machining_tasks_list',               'Page: /manufacturing/machining/tasks/list/'),

    # Manufacturing — Maintenance
    ('access_manufacturing_maintenance',                'Page: /manufacturing/maintenance/'),
    ('access_manufacturing_maintenance_dashboard',      'Page: /manufacturing/maintenance/dashboard/'),
    ('access_manufacturing_maintenance_fault_requests', 'Page: /manufacturing/maintenance/fault-requests/'),
    ('access_manufacturing_maintenance_reports',        'Page: /manufacturing/maintenance/reports/'),
    ('access_manufacturing_maintenance_reports_faults', 'Page: /manufacturing/maintenance/reports/faults/'),

    # Manufacturing — Other
    ('access_manufacturing',                    'Page: /manufacturing/'),
    ('access_manufacturing_material_tracking',  'Page: /manufacturing/material-tracking/'),
    ('access_manufacturing_projects',           'Page: /manufacturing/projects/'),
    ('access_manufacturing_reports',            'Page: /manufacturing/reports/'),
    ('access_manufacturing_reports_combined_job_costs', 'Page: /manufacturing/reports/combined-job-costs/'),

    # Manufacturing — Subcontracting
    ('access_manufacturing_subcontracting',               'Page: /manufacturing/subcontracting/'),
    ('access_manufacturing_subcontracting_overview',      'Page: /manufacturing/subcontracting/overview/'),
    ('access_manufacturing_subcontracting_statements',    'Page: /manufacturing/subcontracting/statements/'),
    ('access_manufacturing_subcontracting_subcontractors','Page: /manufacturing/subcontracting/subcontractors/'),

    # Manufacturing — Welding
    ('access_manufacturing_welding',                            'Page: /manufacturing/welding/'),
    ('access_manufacturing_welding_reports',                    'Page: /manufacturing/welding/reports/'),
    ('access_manufacturing_welding_reports_cost_analysis',      'Page: /manufacturing/welding/reports/cost-analysis/'),
    ('access_manufacturing_welding_reports_user_work_hours',    'Page: /manufacturing/welding/reports/user-work-hours/'),
    ('access_manufacturing_welding_time_entries',               'Page: /manufacturing/welding/time-entries/'),

    # Planning
    ('access_planning',                         'Page: /planning/'),
    ('access_planning_department_requests',     'Page: /planning/department-requests/'),
    ('access_planning_inventory',               'Page: /planning/inventory/'),
    ('access_planning_inventory_cards',         'Page: /planning/inventory/cards/'),
    ('access_planning_procurement_lines',       'Page: /planning/procurement-lines/'),
    ('access_planning_projects',                'Page: /planning/projects/'),
    ('access_planning_task_templates',          'Page: /planning/task-templates/'),

    # Procurement
    ('access_procurement',                              'Page: /procurement/'),
    ('access_procurement_projects',                     'Page: /procurement/projects/'),
    ('access_procurement_purchase_requests',            'Page: /procurement/purchase-requests/'),
    ('access_procurement_purchase_requests_create',     'Page: /procurement/purchase-requests/create/'),
    ('access_procurement_purchase_requests_pending',    'Page: /procurement/purchase-requests/pending/'),
    ('access_procurement_purchase_requests_registry',   'Page: /procurement/purchase-requests/registry/'),
    ('access_procurement_reports',                      'Page: /procurement/reports/'),
    ('access_procurement_reports_items',                'Page: /procurement/reports/items/'),
    ('access_procurement_reports_staff',                'Page: /procurement/reports/staff/'),
    ('access_procurement_reports_suppliers',            'Page: /procurement/reports/suppliers/'),
    ('access_procurement_suppliers',                    'Page: /procurement/suppliers/'),
    ('access_procurement_suppliers_list',               'Page: /procurement/suppliers/list/'),
    ('access_procurement_suppliers_payment_terms',      'Page: /procurement/suppliers/payment-terms/'),

    # Projects
    ('access_projects',             'Page: /projects/'),
    ('access_projects_cost_table',  'Page: /projects/cost-table/'),
    ('access_projects_tracking',    'Page: /projects/project-tracking/'),

    # Quality Control
    ('access_quality_control',              'Page: /quality-control/'),
    ('access_quality_control_cost_lines',   'Page: /quality-control/cost-lines/'),
    ('access_quality_control_ncrs',         'Page: /quality-control/ncrs/'),
    ('access_quality_control_qc_reviews',   'Page: /quality-control/qc-reviews/'),

    # Sales
    ('access_sales',            'Page: /sales/'),
    ('access_sales_catalog',    'Page: /sales/catalog/'),
    ('access_sales_cost_table', 'Page: /sales/cost-table/'),
    ('access_sales_customers',  'Page: /sales/customers/'),
    ('access_sales_offers',     'Page: /sales/offers/'),
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
