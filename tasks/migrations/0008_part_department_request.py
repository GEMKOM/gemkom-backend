# Generated manually for Part.department_request FK

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('planning', '0009_planningrequestitem_delivered_at_and_more'),
        ('tasks', '0007_timer_related_fault_timer_timer_type_downtimereason_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='part',
            name='department_request',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='converted_parts',
                to='planning.departmentrequest',
            ),
        ),
    ]
