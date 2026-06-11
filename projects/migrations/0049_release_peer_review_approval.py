import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('projects', '0048_alter_departmenttasktemplateitem_task_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='technicaldrawingrelease',
            name='auto_complete_design_task',
            field=models.BooleanField(
                default=True,
                help_text='Ana tasarım görevini yayınlandığında otomatik tamamla.',
            ),
        ),
        migrations.AddField(
            model_name='technicaldrawingrelease',
            name='supersedes',
            field=models.ForeignKey(
                blank=True,
                help_text='Revizyon tamamlama akışında yerini aldığı in_revision yayın.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='superseded_by',
                to='projects.technicaldrawingrelease',
            ),
        ),
        migrations.AlterField(
            model_name='technicaldrawingrelease',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending_approval', 'Onay Bekliyor'),
                    ('rejected', 'Reddedildi'),
                    ('released', 'Yayınlandı'),
                    ('in_revision', 'Revizyon Yapılıyor'),
                    ('superseded', 'Güncelliğini Kaybetti'),
                ],
                db_index=True,
                default='pending_approval',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='TechnicalDrawingReleaseApproval',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('decision', models.CharField(choices=[('approved', 'Onaylandı'), ('rejected', 'Reddedildi')], max_length=20)),
                ('comment', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('approver', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='drawing_release_approvals', to=settings.AUTH_USER_MODEL)),
                ('release', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='approvals', to='projects.technicaldrawingrelease')),
            ],
            options={
                'verbose_name': 'Çizim Yayını Onayı',
                'verbose_name_plural': 'Çizim Yayını Onayları',
                'ordering': ['created_at'],
                'unique_together': {('release', 'approver')},
            },
        ),
    ]
