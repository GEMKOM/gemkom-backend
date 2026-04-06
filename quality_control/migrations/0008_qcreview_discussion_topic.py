from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0038_add_on_update_cascade_joborder'),
        ('quality_control', '0007_remove_ncr_quality_con_assigne_b896fb_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='qcreview',
            name='discussion_topic',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='qc_reviews',
                to='projects.joborderdiscussiontopic',
            ),
        ),
    ]
