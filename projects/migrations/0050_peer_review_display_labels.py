from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0049_release_peer_review_approval'),
    ]

    operations = [
        migrations.AlterField(
            model_name='technicaldrawingrelease',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending_approval', 'İnceleme Bekliyor'),
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
        migrations.AlterField(
            model_name='technicaldrawingreleaseapproval',
            name='decision',
            field=models.CharField(
                choices=[('approved', 'Olumlu'), ('rejected', 'Reddedildi')],
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name='technicaldrawingreleaseapproval',
            options={
                'ordering': ['created_at'],
                'verbose_name': 'Çizim Yayını Değerlendirmesi',
                'verbose_name_plural': 'Çizim Yayını Değerlendirmeleri',
            },
        ),
    ]
