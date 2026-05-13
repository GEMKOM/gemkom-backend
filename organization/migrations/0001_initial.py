from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('users', '0037_add_birth_date_to_userprofile'),
    ]

    operations = [
        migrations.CreateModel(
            name='Department',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=50, unique=True)),
                ('name_tr', models.CharField(max_length=100)),
                ('name_en', models.CharField(blank=True, max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Departman',
                'verbose_name_plural': 'Departmanlar',
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='Position',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=150)),
                ('level', models.PositiveSmallIntegerField(
                    help_text='Authority level. Lower = more authority. 1=board, 2=GM, 3=dept-director, 4=manager/chief, 5=specialist, 6=staff.'
                )),
                ('is_active', models.BooleanField(default=True)),
                ('department', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='positions',
                    to='organization.department',
                )),
                ('parent', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='direct_reports',
                    to='organization.position',
                    help_text='The position this one reports to.',
                )),
                ('permissions', models.ManyToManyField(
                    blank=True,
                    related_name='positions',
                    to='users.permissionmeta',
                )),
            ],
            options={
                'verbose_name': 'Pozisyon',
                'verbose_name_plural': 'Pozisyonlar',
                'ordering': ['level', 'department__code', 'title'],
            },
        ),
    ]
