from django.db import migrations, models
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    UserGroup = apps.get_model('organization', 'UserGroup')
    for group in UserGroup.objects.all():
        group.slug = slugify(group.name)
        group.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0005_usergroup'),
    ]

    operations = [
        migrations.AddField(
            model_name='usergroup',
            name='slug',
            field=models.SlugField(
                max_length=100,
                blank=True,
                default='',
                help_text="Machine-readable identifier (e.g. 'planning', 'management'). Auto-derived from name if left blank.",
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='usergroup',
            constraint=models.UniqueConstraint(fields=['slug'], name='organization_usergroup_slug_unique'),
        ),
    ]
