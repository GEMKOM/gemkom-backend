"""
Seed the crane/platform catalog + initial rates from the vendor price sheet
(Bacanaklar Vinç quote dated 2025-09-16, TRY, VAT excluded), and the
"Vinç Koordinasyon" user group (members are position-derived; attach
positions via the existing UserGroup admin UI).
"""
from datetime import date
from decimal import Decimal

from django.db import migrations

QUOTE_DATE = date(2025, 9, 16)
RIGGER_FEE = Decimal('3250')

# (name, category, sort_order, price_up_to_3h, price_up_to_8h, price_per_day, transport_fee, rigger_fee, note)
SEED_ROWS = [
    ('26 Mt Sepetli Vinç',            'basket_crane',         10, '6000',  '8000',  None,   None,   RIGGER_FEE, ''),
    ('32-36 Mt Sepetli Vinç',         'basket_crane',         20, '9000',  '15000', None,   None,   RIGGER_FEE,
     "Teklifte ikinci fiyat 'sonraki saatler' olarak geçiyor"),
    ('40/45 Mt Sepetli Vinç',         'basket_crane',         30, '15000', '20000', None,   None,   RIGGER_FEE, ''),
    ('52 Mt Sepetli Vinç',            'basket_crane',         40, None,    '30000', None,   None,   RIGGER_FEE, ''),
    ('5/10 Ton Kamyon Üstü Vinç',     'truck_crane',          50, '6000',  '10000', None,   None,   RIGGER_FEE, ''),
    ('20/35 Ton Kamyon Üstü Vinç',    'truck_crane',          60, '10000', '15000', None,   None,   RIGGER_FEE, ''),
    ('40/45 Ton Kamyon Üstü Vinç',    'truck_crane',          70, '15000', '20000', None,   None,   RIGGER_FEE, ''),
    ('60/80 Ton Kamyon Üstü Vinç',    'truck_crane',          80, '22500', '32500', None,   None,   RIGGER_FEE, ''),
    ('95/100 Ton Kamyon Üstü Vinç',   'truck_crane',          90, None,    '40000', None,   None,   RIGGER_FEE, ''),
    ('100/120 Tonluk Mobil Vinç',     'mobile_crane',        100, None,    '45000', None,   None,   RIGGER_FEE, ''),
    ('220 Tonluk Mobil Vinç',         'mobile_crane',        110, None,    '55000', None,   None,   RIGGER_FEE, ''),
    ('300 Tonluk Mobil Vinç',         'mobile_crane',        120, None,    '65000', None,   None,   RIGGER_FEE, ''),
    ('08-10 mt Akülü Makaslı Platform', 'scissor_platform',  130, None,    None,    '1500', '4000', None, 'Nakliye gidiş-dönüş'),
    ('12 mt Akülü Makaslı Platform',    'scissor_platform',  140, None,    None,    '1700', '4000', None, 'Nakliye gidiş-dönüş'),
    ('14 mt Akülü Makaslı Platform',    'scissor_platform',  150, None,    None,    '2000', '4000', None, 'Nakliye gidiş-dönüş'),
    ('16 mt Akülü Makaslı Platform',    'scissor_platform',  160, None,    None,    '2100', '4000', None, 'Nakliye gidiş-dönüş'),
    ('13-16 Mt Akülü Eklemli Platform', 'articulated_platform', 170, None, None,    '5000', '4500', None, 'Nakliye gidiş-dönüş'),
]

COORDINATION_GROUP_NAME = 'Vinç Koordinasyon'
COORDINATION_GROUP_SLUG = 'vinc-koordinasyon'


def seed(apps, schema_editor):
    CraneType = apps.get_model('cranes', 'CraneType')
    CraneRate = apps.get_model('cranes', 'CraneRate')
    UserGroup = apps.get_model('organization', 'UserGroup')

    for (name, category, sort_order, p3h, p8h, per_day, transport, rigger, note) in SEED_ROWS:
        crane_type, _ = CraneType.objects.get_or_create(
            name=name,
            defaults={'category': category, 'sort_order': sort_order, 'is_active': True},
        )
        CraneRate.objects.get_or_create(
            crane_type=crane_type,
            effective_from=QUOTE_DATE,
            defaults={
                'currency': 'TRY',
                'price_up_to_3h': Decimal(p3h) if p3h else None,
                'price_up_to_8h': Decimal(p8h) if p8h else None,
                'price_per_day': Decimal(per_day) if per_day else None,
                'transport_fee': Decimal(transport) if transport else None,
                'rigger_fee': rigger,
                'note': note,
            },
        )

    UserGroup.objects.get_or_create(
        slug=COORDINATION_GROUP_SLUG,
        defaults={
            'name': COORDINATION_GROUP_NAME,
            'description': 'Onaylanan vinç/platform taleplerini organize eden ve tamamlanınca fiili maliyeti giren ekip.',
            'is_active': True,
        },
    )


def unseed(apps, schema_editor):
    CraneType = apps.get_model('cranes', 'CraneType')
    CraneRate = apps.get_model('cranes', 'CraneRate')
    UserGroup = apps.get_model('organization', 'UserGroup')

    names = [row[0] for row in SEED_ROWS]
    CraneRate.objects.filter(crane_type__name__in=names, effective_from=QUOTE_DATE).delete()
    CraneType.objects.filter(name__in=names, requests__isnull=True).delete()
    UserGroup.objects.filter(slug=COORDINATION_GROUP_SLUG).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cranes', '0001_initial'),
        ('organization', '0007_remove_usergroup_organization_usergroup_slug_unique_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
