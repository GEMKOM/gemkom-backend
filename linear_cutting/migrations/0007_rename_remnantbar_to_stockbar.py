from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('linear_cutting', '0006_linearcuttingremnantbar'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Rename model (also renames the underlying DB table)
        migrations.RenameModel(
            old_name='LinearCuttingRemnantBar',
            new_name='LinearCuttingStockBar',
        ),

        # 2. Remove fields that no longer exist
        migrations.RemoveField(
            model_name='linearcuttingstockbar',
            name='status',
        ),
        migrations.RemoveField(
            model_name='linearcuttingstockbar',
            name='consumed_at',
        ),

        # 3. Change session FK: SET_NULL → CASCADE, make it required (null=False)
        migrations.AlterField(
            model_name='linearcuttingstockbar',
            name='session',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='stock_bars',
                to='linear_cutting.linearcuttingsession',
            ),
        ),

        # 4. Rename created_by → declared_by and created_at → declared_at
        migrations.RenameField(
            model_name='linearcuttingstockbar',
            old_name='created_by',
            new_name='declared_by',
        ),
        migrations.RenameField(
            model_name='linearcuttingstockbar',
            old_name='created_at',
            new_name='declared_at',
        ),

        # 5. Update related_name on item FK
        migrations.AlterField(
            model_name='linearcuttingstockbar',
            name='item',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='lc_stock_bars',
                to='procurement.item',
            ),
        ),

        # 6. Add stock_entry_complete flag to session
        migrations.AddField(
            model_name='linearcuttingsession',
            name='stock_entry_complete',
            field=models.BooleanField(default=False),
        ),
    ]
