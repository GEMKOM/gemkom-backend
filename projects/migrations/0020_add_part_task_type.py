from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0019_departmenttasktemplateitem_task_type_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='joborderdepartmenttask',
            name='task_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('cnc_cutting', 'CNC Kesim'),
                    ('machining', 'Talaşlı İmalat'),
                    ('welding', 'Kaynaklı İmalat'),
                    ('part', 'Parça'),
                ],
                db_index=True,
                help_text='Special task type — drives progress calculation and subcontracting logic. Leave blank for regular tasks.',
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='departmenttasktemplateitem',
            name='task_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('cnc_cutting', 'CNC Kesim'),
                    ('machining', 'Talaşlı İmalat'),
                    ('welding', 'Kaynaklı İmalat'),
                    ('part', 'Parça'),
                ],
                help_text='Special task type — leave blank for regular tasks.',
                max_length=20,
                null=True,
            ),
        ),
    ]
