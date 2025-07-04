# Generated by Django 5.2.3 on 2025-06-20 19:54

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('user_id', models.CharField(max_length=100, primary_key=True, serialize=False)),
                ('password', models.CharField(blank=True, max_length=100, null=True)),
                ('is_admin', models.BooleanField(default=False)),
                ('is_online', models.BooleanField(default=False)),
                ('team', models.CharField(blank=True, max_length=100, null=True)),
            ],
            options={
                'db_table': 'users',
            },
        ),
    ]
