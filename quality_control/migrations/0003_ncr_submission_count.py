from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quality_control', '0002_add_part_data_to_qcreview'),
    ]

    operations = [
        migrations.AddField(
            model_name='ncr',
            name='submission_count',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
