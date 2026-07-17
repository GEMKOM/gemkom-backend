# Adds per-entry decision fields (partial approval), request resubmit counter,
# and the entry status index. The operations M2M is added by the separate
# 0004_overtimeentry_add_operations_m2m migration (already deployed), so it is
# intentionally NOT recreated here. This migration merges the two 0004 branches.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('overtime', '0004_remove_team_index'),
        ('overtime', '0004_overtimeentry_add_operations_m2m'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='overtimeentry',
            name='decided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='overtimeentry',
            name='decided_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='overtimeentry',
            name='status',
            field=models.CharField(choices=[('pending', 'Bekliyor'), ('approved', 'Onaylandı'), ('rejected', 'Reddedildi')], default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='overtimerequest',
            name='resubmit_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name='overtimeentry',
            index=models.Index(fields=['status'], name='overtime_ov_status_a1db31_idx'),
        ),
    ]
