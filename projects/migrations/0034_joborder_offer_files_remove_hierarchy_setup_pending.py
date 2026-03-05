from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0033_joborder_source_offer'),
        ('sales', '0006_salesoffer_incoterms'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='joborder',
            name='hierarchy_setup_pending',
        ),
        migrations.AddField(
            model_name='joborder',
            name='offer_files',
            field=models.ManyToManyField(
                blank=True,
                related_name='attached_job_orders',
                to='sales.salesofferfile',
            ),
        ),
    ]
