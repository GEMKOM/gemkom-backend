from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0012_remove_approvalpolicy_is_rolling_mill'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='approvalpolicy',
            name='priority_in',
        ),
    ]
