from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0005_salesofferitem_unit_price_salesofferitem_weight_kg'),
    ]

    operations = [
        migrations.AddField(
            model_name='salesoffer',
            name='incoterms',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Teslim şekli (e.g. EXW, FOB, CIF)',
                max_length=100,
            ),
            preserve_default=False,
        ),
    ]
