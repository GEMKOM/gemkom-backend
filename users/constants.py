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
