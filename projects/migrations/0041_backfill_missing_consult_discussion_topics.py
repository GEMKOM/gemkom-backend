from django.db import migrations


def backfill_missing_consult_topics(apps, schema_editor):
    JobOrderDepartmentTask = apps.get_model('projects', 'JobOrderDepartmentTask')
    JobOrderDiscussionTopic = apps.get_model('projects', 'JobOrderDiscussionTopic')

    tasks = JobOrderDepartmentTask.objects.filter(
        task_type='sales_consult',
    ).exclude(
        discussion_topic__is_deleted=False,
    )

    for task in tasks:
        JobOrderDiscussionTopic.objects.create(
            task=task,
            job_order=None,
            title=f'Danışmanlık: {task.title}',
            content='',
            topic_type='general',
            priority='normal',
            created_by=task.created_by,
        )


def reverse_backfill(apps, schema_editor):
    pass  # non-destructive reverse


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0040_backfill_consult_discussion_topics'),
    ]

    operations = [
        migrations.RunPython(backfill_missing_consult_topics, reverse_code=reverse_backfill),
    ]
