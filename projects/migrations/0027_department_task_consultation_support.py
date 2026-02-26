import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0026_add_paint_material_rate'),
        ('sales', '0001_initial'),
    ]

    operations = [
        # 1. Add hierarchy_setup_pending to JobOrder
        migrations.AddField(
            model_name='joborder',
            name='hierarchy_setup_pending',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'True when created from a sales offer without catalog items. '
                    'Hierarchy must be configured manually.'
                ),
            ),
        ),

        # 2. Make job_order nullable on JobOrderDepartmentTask
        migrations.AlterField(
            model_name='joborderdepartmenttask',
            name='job_order',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='department_tasks',
                to='projects.joborder',
            ),
        ),

        # 3. Add sales_offer FK
        migrations.AddField(
            model_name='joborderdepartmenttask',
            name='sales_offer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='department_tasks',
                to='sales.salesoffer',
            ),
        ),

        # 4. Add shared_files M2M
        migrations.AddField(
            model_name='joborderdepartmenttask',
            name='shared_files',
            field=models.ManyToManyField(
                blank=True,
                related_name='shared_in_tasks',
                to='sales.salesofferfile',
            ),
        ),

        # 5. Add index for sales_offer + department lookups
        migrations.AddIndex(
            model_name='joborderdepartmenttask',
            index=models.Index(
                fields=['sales_offer', 'department'],
                name='projects_task_salesoffer_dept_idx',
            ),
        ),
    ]
