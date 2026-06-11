from django.db import migrations, models


def backfill_release_review_topics(apps, schema_editor):
    JobOrderDiscussionTopic = apps.get_model('projects', 'JobOrderDiscussionTopic')
    TechnicalDrawingRelease = apps.get_model('projects', 'TechnicalDrawingRelease')

    review_topic_ids = TechnicalDrawingRelease.objects.filter(
        status__in=['pending_approval', 'rejected'],
        release_topic_id__isnull=False,
    ).values_list('release_topic_id', flat=True)

    JobOrderDiscussionTopic.objects.filter(
        id__in=review_topic_ids,
        topic_type='drawing_release',
    ).update(topic_type='release_review')


def revert_release_review_topics(apps, schema_editor):
    JobOrderDiscussionTopic = apps.get_model('projects', 'JobOrderDiscussionTopic')
    JobOrderDiscussionTopic.objects.filter(topic_type='release_review').update(
        topic_type='drawing_release'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0050_peer_review_display_labels'),
    ]

    operations = [
        migrations.AlterField(
            model_name='joborderdiscussiontopic',
            name='topic_type',
            field=models.CharField(
                choices=[
                    ('general', 'Genel'),
                    ('drawing_release', 'Çizim Yayını'),
                    ('release_review', 'Çizim İncelemesi'),
                    ('revision_request', 'Revizyon Talebi'),
                ],
                db_index=True,
                default='general',
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_release_review_topics, revert_release_review_topics),
    ]
