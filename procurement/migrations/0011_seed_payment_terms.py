from django.db import migrations

def seed_terms(apps, schema_editor):
    PaymentTerms = apps.get_model('procurement', 'PaymentTerms')
    presets = [
        {
            "name": "100% Peşin",
            "code": "advance_100",
            "is_custom": False,
            "default_lines": [
                {"percentage": 100.00, "label": "Peşin", "basis": "immediate", "offset_days": 0},
            ],
        },
        {
            "name": "30% Peşin / 70% Teslimde",
            "code": "split_30_70_delivery",
            "is_custom": False,
            "default_lines": [
                {"percentage": 30.00, "label": "Peşin", "basis": "immediate", "offset_days": 0},
                {"percentage": 70.00, "label": "Teslimde", "basis": "after_delivery", "offset_days": 0},
            ],
        },
        {
            "name": "Net 30 (Faturadan 30 gün sonra)",
            "code": "net_30",
            "is_custom": False,
            "default_lines": [
                {"percentage": 100.00, "label": "Net 30", "basis": "after_invoice", "offset_days": 30},
            ],
        },
        {
            "name": "Net 60 (Faturadan 60 gün sonra)",
            "code": "net_60",
            "is_custom": False,
            "default_lines": [
                {"percentage": 100.00, "label": "Net 60", "basis": "after_invoice", "offset_days": 60},
            ],
        },
        {
            "name": "Özel",
            "code": "custom",
            "is_custom": True,
            "default_lines": [],
        },
    ]
    for p in presets:
        PaymentTerms.objects.get_or_create(code=p["code"], defaults=p)

def unseed_terms(apps, schema_editor):
    PaymentTerms = apps.get_model('procurement', 'PaymentTerms')
    PaymentTerms.objects.filter(code__in=[
        "advance_100", "split_30_70_delivery", "net_30", "net_60", "custom"
    ]).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('procurement', '0010_remove_supplieroffer_payment_method_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_terms, unseed_terms),
    ]