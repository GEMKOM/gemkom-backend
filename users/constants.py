# Canonical Turkish display names for Django Groups used as roles.
# Keep this in sync with the group names created in migration 0023.
GROUP_DISPLAY_NAMES: dict[str, str] = {
    'planning_team':           'Planlama Ekibi',
    'planning_manager':        'Planlama Yöneticisi',
    'procurement_team':        'Satınalma Ekibi',
    'finance_team':            'Finans Ekibi',
    'accounting_team':         'Muhasebe Ekibi',
    'management_team':         'Yönetim',
    'machining_team':          'İşleme Ekibi',
    'welding_team':            'Kaynak Ekibi',
    'cutting_team':            'CNC Kesim Ekibi',
    'sales_team':              'Satış Ekibi',
    'warehouse_team':          'Depo Ekibi',
    'qualitycontrol_team':     'Kalite Kontrol Ekibi',
    'logistics_team':          'Lojistik Ekibi',
    'hr_team':                 'İnsan Kaynakları',
    'design_team':             'Dizayn Ekibi',
    'manufacturing_team':      'Üretim Ekibi',
    'maintenance_team':        'Bakım Ekibi',
}

# Which groups belong to each portal.
# Used for filtering, dropdowns, and notification routing.
OFFICE_GROUPS: list[str] = [
    'planning_team',
    'planning_manager',
    'procurement_team',
    'finance_team',
    'accounting_team',
    'management_team',
    'sales_team',
    'qualitycontrol_team',
    'logistics_team',
    'hr_team',
    'design_team',
]

WORKSHOP_GROUPS: list[str] = [
    'machining_team',
    'welding_team',
    'cutting_team',
    'warehouse_team',
    'manufacturing_team',
    'maintenance_team',
]

# Per-section permission groupings.
# Used to populate the `section` field in GET /users/permissions/.
# Permissions not listed in any section get section=null (functional permissions).

WORKSHOP_PERMISSIONS: list[str] = [
    'access_cnc_cutting',
    'access_cnc_cutting_tasks',
    'access_department_requests',
    'access_department_requests_create',
    'access_machining',
    'access_machining_tasks',
    'access_maintenance',
    'access_maintenance_create',
    'access_maintenance_list',
    'access_warehouse',
    'access_warehouse_inventory_allocation',
    'access_warehouse_material_tracking',
    'access_warehouse_weight_reduction',
]

MANUFACTURING_PERMISSIONS: list[str] = [
    'access_manufacturing',
    'access_manufacturing_material_tracking',
    'access_manufacturing_projects',
    'access_manufacturing_reports',
    'access_manufacturing_reports_combined_job_costs',
    'access_manufacturing_cnc_cutting',
    'access_manufacturing_cnc_cutting_capacity',
    'access_manufacturing_cnc_cutting_capacity_planning',
    'access_manufacturing_cnc_cutting_cuts',
    'access_manufacturing_cnc_cutting_dashboard',
    'access_manufacturing_cnc_cutting_remnants',
    'access_manufacturing_cnc_cutting_reports',
    'access_manufacturing_cnc_cutting_reports_finished_timers',
    'access_manufacturing_cnc_cutting_reports_parts_search',
    'access_manufacturing_machining',
    'access_manufacturing_machining_capacity',
    'access_manufacturing_machining_capacity_planning',
    'access_manufacturing_machining_create_task',
    'access_manufacturing_machining_dashboard',
    'access_manufacturing_machining_reports',
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
    'access_manufacturing_maintenance',
    'access_manufacturing_maintenance_dashboard',
    'access_manufacturing_maintenance_fault_requests',
    'access_manufacturing_maintenance_reports',
    'access_manufacturing_maintenance_reports_faults',
    'access_manufacturing_subcontracting_overview',
    'access_manufacturing_subcontracting_statements',
    'access_manufacturing_subcontracting_subcontractors',
    'access_manufacturing_welding',
    'access_manufacturing_welding_reports',
    'access_manufacturing_welding_reports_cost_analysis',
    'access_manufacturing_welding_reports_user_work_hours',
    'access_manufacturing_welding_time_entries',
]

DESIGN_PERMISSIONS: list[str] = [
    'access_design',
    'access_design_projects',
    'access_design_revision_requests',
]

FINANCE_PERMISSIONS: list[str] = [
    'access_finance',
    'access_finance_purchase_orders',
    'access_finance_reports',
    'access_finance_reports_executive_overview',
    'access_finance_reports_projects',
]

GENERAL_PERMISSIONS: list[str] = [
    'access_general',
    'access_general_department_requests',
    'access_general_department_requests_list',
    'access_general_department_requests_pending',
    'access_general_machines',
    'access_general_overtime',
    'access_general_overtime_pending',
    'access_general_overtime_registry',
    'access_general_overtime_users',
    'access_general_users',
]

HUMAN_RESOURCES_PERMISSIONS: list[str] = [
    'access_human_resources',
    'access_human_resources_wages',
]

IT_PERMISSIONS: list[str] = [
    'access_it',
    'access_it_inventory',
    'access_it_notifications',
    'access_it_password_resets',
    'access_it_permissions',
]

LOGISTICS_PERMISSIONS: list[str] = [
    'access_logistics',
    'access_logistics_cost_lines',
    'access_logistics_projects',
]

MANAGEMENT_PERMISSIONS: list[str] = [
    'access_management',
    'access_management_dashboard',
]

PLANNING_PERMISSIONS: list[str] = [
    'access_planning',
    'access_planning_department_requests',
    'access_planning_inventory',
    'access_planning_inventory_cards',
    'access_planning_procurement_lines',
    'access_planning_projects',
    'access_planning_task_templates',
]

PROCUREMENT_PERMISSIONS: list[str] = [
    'access_procurement',
    'access_procurement_projects',
    'access_procurement_purchase_requests',
    'access_procurement_purchase_requests_create',
    'access_procurement_purchase_requests_pending',
    'access_procurement_purchase_requests_registry',
    'access_procurement_reports',
    'access_procurement_reports_items',
    'access_procurement_reports_staff',
    'access_procurement_reports_suppliers',
    'access_procurement_suppliers',
    'access_procurement_suppliers_list',
    'access_procurement_suppliers_payment_terms',
]

PROJECTS_PERMISSIONS: list[str] = [
    'access_projects',
    'access_projects_cost_table',
    'access_projects_tracking',
]

QUALITY_CONTROL_PERMISSIONS: list[str] = [
    'access_quality_control',
    'access_quality_control_cost_lines',
    'access_quality_control_ncrs',
    'access_quality_control_qc_reviews',
]

SALES_PERMISSIONS: list[str] = [
    'access_sales',
    'access_sales_catalog',
    'access_sales_cost_table',
    'access_sales_customers',
    'access_sales_offers',
]

# Lookup map: codename → section name
PERMISSION_SECTION_MAP: dict[str, str] = {
    codename: section
    for section, codenames in [
        ('workshop',        WORKSHOP_PERMISSIONS),
        ('manufacturing',   MANUFACTURING_PERMISSIONS),
        ('design',          DESIGN_PERMISSIONS),
        ('finance',         FINANCE_PERMISSIONS),
        ('general',         GENERAL_PERMISSIONS),
        ('human_resources', HUMAN_RESOURCES_PERMISSIONS),
        ('it',              IT_PERMISSIONS),
        ('logistics',       LOGISTICS_PERMISSIONS),
        ('management',      MANAGEMENT_PERMISSIONS),
        ('planning',        PLANNING_PERMISSIONS),
        ('procurement',     PROCUREMENT_PERMISSIONS),
        ('projects',        PROJECTS_PERMISSIONS),
        ('quality_control', QUALITY_CONTROL_PERMISSIONS),
        ('sales',           SALES_PERMISSIONS),
    ]
    for codename in codenames
}
