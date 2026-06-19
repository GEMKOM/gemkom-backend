import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0052_jobordercostsummary_estimated_total_cost'),
    ]

    operations = [
        migrations.AddField(
            model_name='joborder',
            name='phase_number',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Üretim faz numarası (örn. 270-01/P1 için 1). Faz işleri için doludur.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='joborder',
            name='source_job_order',
            field=models.ForeignKey(
                blank=True,
                help_text='Bu fazın türetildiği mühendislik iş emri.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='phase_mirrors',
                to='projects.joborder',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='joborder',
            unique_together={('source_job_order', 'phase_number')},
        ),
    ]
