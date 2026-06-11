from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0051_release_review_topic_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobordercostsummary',
            name='estimated_total_cost',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Cached projected full cost at 100% (EUR); refreshed on cost recompute',
                max_digits=16,
                null=True,
            ),
        ),
    ]
