from django.db import migrations, models
import django.db.models.deletion


def seed_configs(apps, schema_editor):
    from notifications.service import NOTIFICATION_CONFIG_DEFAULTS
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationRoute  = apps.get_model('notifications', 'NotificationRoute')

    # Build a map of existing route data to carry over
    route_map = {}
    for route in NotificationRoute.objects.prefetch_related('users'):
        route_map[route.notification_type] = route

    for ntype, d in NOTIFICATION_CONFIG_DEFAULTS.items():
        route = route_map.get(ntype)
        # If the route had a custom link, use it as link_template
        link_template = d['link']
        if route and route.link:
            link_template = route.link

        cfg, _ = NotificationConfig.objects.get_or_create(
            notification_type=ntype,
            defaults={
                'title_template': d['title'],
                'body_template':  d['body'],
                'link_template':  link_template,
                'available_vars': d['vars'],
                'teams':   route.teams   if route else [],
                'enabled': route.enabled if route else True,
            },
        )

        # Copy users M2M from existing route
        if route:
            cfg.users.set(route.users.all())


def unseed_configs(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0004_add_route_teams'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_type', models.CharField(
                    choices=[
                        ('pr_approval_requested', 'Satınalma Onayı Bekleniyor'),
                        ('pr_approved', 'Satınalma Talebi Onaylandı'),
                        ('pr_rejected', 'Satınalma Talebi Reddedildi'),
                        ('pr_po_created', 'Satınalma Siparişi Oluşturuldu'),
                        ('ot_approval_requested', 'Mesai Onayı Bekleniyor'),
                        ('ot_approved', 'Mesai Talebi Onaylandı'),
                        ('ot_rejected', 'Mesai Talebi Reddedildi'),
                        ('qc_review_submitted', 'KK İncelemesi Gönderildi'),
                        ('qc_review_approved', 'KK İncelemesi Onaylandı'),
                        ('qc_review_rejected', 'KK İncelemesi Reddedildi'),
                        ('ncr_created', 'NCR Oluşturuldu'),
                        ('ncr_submitted', 'NCR Onaya Gönderildi'),
                        ('ncr_approved', 'NCR Onaylandı'),
                        ('ncr_rejected', 'NCR Reddedildi'),
                        ('ncr_assigned', 'NCR Atandı'),
                        ('sales_approval_requested', 'Satış Teklifi Onay Bekliyor'),
                        ('sales_approved', 'Satış Teklifi Onaylandı'),
                        ('sales_rejected', 'Satış Teklifi Reddedildi'),
                        ('sales_consultation', 'Satış Danışma Talebi'),
                        ('sales_converted', 'Teklif İş Emrine Dönüştürüldü'),
                        ('sub_approval_requested', 'Taşeron Hakedişi Onay Bekliyor'),
                        ('sub_approved', 'Taşeron Hakedişi Onaylandı'),
                        ('sub_rejected', 'Taşeron Hakedişi Reddedildi'),
                        ('plan_approval_requested', 'Departman Talebi Onay Bekliyor'),
                        ('plan_approved', 'Departman Talebi Onaylandı'),
                        ('plan_rejected', 'Departman Talebi Reddedildi'),
                        ('plan_dr_approved', 'Departman Talebi Planlama Onayladı'),
                        ('drawing_released', 'Çizim Yayınlandı'),
                        ('revision_requested', 'Revizyon Talep Edildi'),
                        ('revision_approved', 'Revizyon Onaylandı'),
                        ('revision_completed', 'Revizyon Tamamlandı'),
                        ('revision_rejected', 'Revizyon Reddedildi'),
                        ('job_on_hold', 'İş Beklemede'),
                        ('job_resumed', 'İş Devam Ediyor'),
                        ('topic_mention', 'Konuda Etiketlendiniz'),
                        ('comment_mention', 'Yorumda Etiketlendiniz'),
                        ('new_comment', 'Yeni Yorum'),
                        ('password_reset', 'Parola Sıfırlama Talebi'),
                    ],
                    db_index=True,
                    max_length=60,
                    unique=True,
                )),
                ('title_template', models.CharField(max_length=500)),
                ('body_template', models.TextField(blank=True)),
                ('link_template', models.CharField(blank=True, max_length=500)),
                ('available_vars', models.JSONField(blank=True, default=list)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('teams', models.JSONField(blank=True, default=list)),
                ('enabled', models.BooleanField(default=True)),
                ('users', models.ManyToManyField(
                    blank=True,
                    related_name='notification_configs',
                    to='auth.user',
                )),
            ],
            options={
                'ordering': ['notification_type'],
            },
        ),
        migrations.RunPython(seed_configs, reverse_code=unseed_configs),
    ]
