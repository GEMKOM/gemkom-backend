from __future__ import annotations

from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
        ('subcontracting', '0002_alter_subcontractingpricetier_price_per_kg'),
    ]

    operations = [
        # Step 1: delete any existing adjustments with no job_order so we can
        # safely make the column NOT NULL (production data shouldn't have any,
        # but this keeps the migration safe).
        migrations.RunSQL(
            sql="DELETE FROM subcontracting_subcontractorstatementadjustment WHERE job_order_id IS NULL;",
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Step 2: make job_order non-nullable + change on_delete to PROTECT
        migrations.AlterField(
            model_name='subcontractorstatementadjustment',
            name='job_order',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='subcontracting_adjustments',
                to='projects.joborder',
            ),
        ),

        # Step 3: add weight_kg
        migrations.AddField(
            model_name='subcontractorstatementadjustment',
            name='weight_kg',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Applicable weight in kg (optional context, default 0)',
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
    ]
