"""
Data migration: create a JobOrderDiscussionTopic for every existing QCReview
that doesn't already have one, then link it back via discussion_topic.
"""
from django.db import migrations


def create_topics_for_existing_reviews(apps, schema_editor):
    QCReview = apps.get_model('quality_control', 'QCReview')
    JobOrderDiscussionTopic = apps.get_model('projects', 'JobOrderDiscussionTopic')

    reviews = (
        QCReview.objects
        .filter(discussion_topic__isnull=True)
        .select_related('task', 'task__job_order', 'submitted_by')
    )

    for review in reviews:
        task = review.task
        job_order = task.job_order if task else None
        topic = JobOrderDiscussionTopic.objects.create(
            job_order=job_order,
            task=None,
            title=f'KK İncelemesi #{review.id}: {task.title if task else "—"}',
            content='',
            topic_type='general',
            priority='normal',
            created_by=review.submitted_by,
        )
        review.discussion_topic = topic
        review.save(update_fields=['discussion_topic'])


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0044_joborderprogresslog'),
        ('quality_control', '0008_qcreview_discussion_topic'),
    ]

    operations = [
        migrations.RunPython(
            create_topics_for_existing_reviews,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
