from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('overtime', '0003_alter_overtimeentry_user'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='overtimerequest',
            name='overtime_ov_team_7f4a3f_idx',
        ),
    ]
