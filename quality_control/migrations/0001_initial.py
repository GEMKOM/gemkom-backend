import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('approvals', '0006_alter_prapprovalstageinstance_unique_together_and_more'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('projects', '0020_add_part_task_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NCR',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ncr_number', models.CharField(db_index=True, max_length=50, unique=True)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField()),
                ('defect_type', models.CharField(
                    choices=[
                        ('dimensional', 'Boyutsal'),
                        ('surface', 'Yüzey'),
                        ('material', 'Malzeme'),
                        ('welding', 'Kaynak'),
                        ('machining', 'Talaşlı İmalat'),
                        ('assembly', 'Montaj'),
                        ('documentation', 'Dokümantasyon'),
                        ('other', 'Diğer'),
                    ],
                    default='other',
                    max_length=30,
                )),
                ('severity', models.CharField(
                    choices=[
                        ('minor', 'Minör'),
                        ('major', 'Majör'),
                        ('critical', 'Kritik'),
                    ],
                    db_index=True,
                    default='minor',
                    max_length=20,
                )),
                ('affected_quantity', models.PositiveIntegerField(default=1)),
                ('root_cause', models.TextField(blank=True)),
                ('corrective_action', models.TextField(blank=True)),
                ('disposition', models.CharField(
                    choices=[
                        ('rework', 'Yeniden İşleme'),
                        ('scrap', 'Hurda'),
                        ('accept_as_is', 'Olduğu Gibi Kabul'),
                        ('pending', 'Karar Bekliyor'),
                    ],
                    default='pending',
                    max_length=20,
                )),
                ('assigned_team', models.CharField(blank=True, max_length=50)),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Taslak'),
                        ('submitted', 'Gönderildi'),
                        ('approved', 'Onaylandı'),
                        ('rejected', 'Reddedildi'),
                        ('closed', 'Kapatıldı'),
                    ],
                    db_index=True,
                    default='draft',
                    max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_members', models.ManyToManyField(
                    blank=True,
                    related_name='assigned_ncrs',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='created_ncrs',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('department_task', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='ncrs',
                    to='projects.joborderdepartmenttask',
                )),
                ('detected_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='detected_ncrs',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('job_order', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='ncrs',
                    to='projects.joborder',
                )),
            ],
            options={
                'verbose_name': 'Uygunsuzluk Raporu',
                'verbose_name_plural': 'Uygunsuzluk Raporları',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='QCReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'İnceleme Bekliyor'),
                        ('approved', 'Onaylandı'),
                        ('rejected', 'Reddedildi'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=20,
                )),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('comment', models.TextField(blank=True)),
                ('ncr', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='source_reviews',
                    to='quality_control.ncr',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reviewed_qc_reviews',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('submitted_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='submitted_qc_reviews',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='qc_reviews',
                    to='projects.joborderdepartmenttask',
                )),
            ],
            options={
                'verbose_name': 'KK İncelemesi',
                'verbose_name_plural': 'KK İncelemeleri',
                'ordering': ['-submitted_at'],
            },
        ),
        migrations.AddField(
            model_name='ncr',
            name='qc_review',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ncrs',
                to='quality_control.qcreview',
            ),
        ),
        migrations.AddIndex(
            model_name='ncr',
            index=models.Index(fields=['job_order', 'status'], name='quality_con_job_ord_726509_idx'),
        ),
        migrations.AddIndex(
            model_name='ncr',
            index=models.Index(fields=['severity', 'status'], name='quality_con_severit_fe17df_idx'),
        ),
        migrations.AddIndex(
            model_name='ncr',
            index=models.Index(fields=['assigned_team', 'status'], name='quality_con_assigne_b896fb_idx'),
        ),
        migrations.AddIndex(
            model_name='qcreview',
            index=models.Index(fields=['task', 'status'], name='quality_con_task_id_4c8dcf_idx'),
        ),
        migrations.AddIndex(
            model_name='qcreview',
            index=models.Index(fields=['status', 'submitted_at'], name='quality_con_status_5f2fdb_idx'),
        ),
    ]
