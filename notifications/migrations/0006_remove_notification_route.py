from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0005_notification_config'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(
            name='NotificationRoute',
        ),
    ]
