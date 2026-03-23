from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0031_add_maintenance_dashboard_permission'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userprofile',
            name='team',
        ),
    ]
