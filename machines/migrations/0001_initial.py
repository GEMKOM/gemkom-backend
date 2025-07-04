# Generated by Django 5.2.3 on 2025-06-26 11:13

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Machine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('machine_type', models.CharField(choices=[('FTB', 'Zemin Tipi Manuel Borwerk'), ('TTB', 'Tabla Tipi Manuel Borwerk'), ('HM', 'Yatay İşleme Merkezi'), ('HT', 'Yatay Tornalama Merkezi'), ('VM', 'Dik İşleme Merkezi'), ('DM', 'Matkap'), ('SM', 'Kama Kanalı Açma Tezgahı'), ('BT', 'Köprü Tipi İşleme Merkezi'), ('ACT', 'AJAN Sac Kesim Tezgahı'), ('ECT', 'ESAB Sac Kesim Tezgahı')], max_length=10)),
                ('used_in', models.CharField(default='machining', max_length=50)),
                ('jira_id', models.IntegerField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('properties', models.JSONField(default=dict)),
            ],
        ),
    ]
