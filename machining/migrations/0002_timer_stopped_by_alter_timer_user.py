# Generated by Django 5.2.3 on 2025-06-27 09:31

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('machining', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='timer',
            name='stopped_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='stopped_timers', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='timer',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='started_timers', to=settings.AUTH_USER_MODEL),
        ),
    ]
