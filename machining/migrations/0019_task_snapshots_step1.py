from django.db import migrations, models
import django.db.models.deletion

def seed_cached_labels(apps, schema_editor):
    JobCostAgg = apps.get_model("machining", "JobCostAgg")
    JobCostAggUser = apps.get_model("machining", "JobCostAggUser")
    # If you already have job_no column on these tables, copy it into job_no_cached.
    if hasattr(JobCostAgg, "job_no") and hasattr(JobCostAgg, "job_no_cached"):
        JobCostAgg.objects.exclude(job_no=None).update(job_no_cached=models.F("job_no"))
    if hasattr(JobCostAggUser, "job_no") and hasattr(JobCostAggUser, "job_no_cached"):
        JobCostAggUser.objects.exclude(job_no=None).update(job_no_cached=models.F("job_no"))

class Migration(migrations.Migration):
    dependencies = [
        ("machining", "0018_jobcostagg_jobcostrecalcqueue_jobcostagguser"),  # replace with your last migration
    ]

    operations = [
        # 1) Add nullable task FKs
        migrations.AddField(
            model_name="jobcostagg",
            name="task",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                to="machining.task",
                null=True,
                related_name="+",
            ),
        ),
        migrations.AddField(
            model_name="jobcostagguser",
            name="task",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="machining.task",
                null=True,
                related_name="+",
            ),
        ),
        migrations.AddField(
            model_name="jobcostrecalcqueue",
            name="task",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                to="machining.task",
                null=True,
                related_name="+",
            ),
        ),

        # 2) Add cached label
        migrations.AddField(
            model_name="jobcostagg",
            name="job_no_cached",
            field=models.CharField(max_length=100, db_index=True, default=""),
        ),
        migrations.AddField(
            model_name="jobcostagguser",
            name="job_no_cached",
            field=models.CharField(max_length=100, db_index=True, default=""),
        ),

        migrations.RunPython(seed_cached_labels, migrations.RunPython.noop),

        # 3) (optional) indexes help when reading by label
        migrations.AddIndex(
            model_name="jobcostagg",
            index=models.Index(fields=["job_no_cached"], name="agg_jobno_idx"),
        ),
        migrations.AddIndex(
            model_name="jobcostagguser",
            index=models.Index(fields=["job_no_cached"], name="agguser_jobno_idx"),
        ),
    ]
