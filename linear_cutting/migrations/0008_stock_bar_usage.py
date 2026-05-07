from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('linear_cutting', '0007_rename_remnantbar_to_stockbar'),
    ]

    operations = [
        migrations.CreateModel(
            name='LinearCuttingStockBarUsage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity_used', models.PositiveIntegerField()),
                ('session', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='stock_bar_usages',
                    to='linear_cutting.linearcuttingsession',
                )),
                ('stock_bar', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='usages',
                    to='linear_cutting.linearcuttingstockbar',
                )),
            ],
            options={
                'unique_together': {('session', 'stock_bar')},
            },
        ),
        migrations.AddField(
            model_name='linearcuttingsession',
            name='used_stock_bars',
            field=models.ManyToManyField(
                blank=True,
                related_name='consuming_sessions',
                through='linear_cutting.LinearCuttingStockBarUsage',
                to='linear_cutting.linearcuttingstockbar',
            ),
        ),
    ]
