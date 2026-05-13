from django.db import migrations

DEPARTMENTS = [
    ('machining',          'Talaşlı İmalat',       'Machining'),
    ('design',             'Dizayn',                'Design'),
    ('logistics',          'Lojistik',              'Logistics'),
    ('procurement',        'Satın Alma',            'Procurement'),
    ('welding',            'Kaynaklı İmalat',       'Welding'),
    ('planning',           'Planlama',              'Planning'),
    ('manufacturing',      'İmalat',                'Manufacturing'),
    ('maintenance',        'Bakım',                 'Maintenance'),
    ('rollingmill',        'Haddehane',             'Rolling Mill'),
    ('qualitycontrol',     'Kalite Kontrol',        'Quality Control'),
    ('cutting',            'CNC Kesim',             'CNC Cutting'),
    ('warehouse',          'Ambar',                 'Warehouse'),
    ('finance',            'Finans',                'Finance'),
    ('management',         'Yönetim',               'Management'),
    ('external_workshops', 'Dış Atölyeler',         'External Workshops'),
    ('human_resources',    'İnsan Kaynakları',      'Human Resources'),
    ('sales',              'Proje Taahhüt',         'Sales & Projects'),
    ('accounting',         'Muhasebe',              'Accounting'),
]


def seed(apps, schema_editor):
    Department = apps.get_model('organization', 'Department')
    for code, name_tr, name_en in DEPARTMENTS:
        Department.objects.get_or_create(
            code=code,
            defaults={'name_tr': name_tr, 'name_en': name_en, 'is_active': True},
        )


def unseed(apps, schema_editor):
    Department = apps.get_model('organization', 'Department')
    codes = [c for c, _, __ in DEPARTMENTS]
    Department.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
