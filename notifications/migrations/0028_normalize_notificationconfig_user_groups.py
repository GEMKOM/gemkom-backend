from django.db import migrations


def normalize_user_groups(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    UserGroup = apps.get_model('organization', 'UserGroup')

    groups = list(UserGroup.objects.filter(is_active=True).values('id', 'name', 'slug'))
    by_id = {str(group['id']): group['id'] for group in groups}
    by_name = {group['name']: group['id'] for group in groups}
    by_slug = {group['slug']: group['id'] for group in groups if group['slug']}

    for cfg in NotificationConfig.objects.exclude(user_groups=[]):
        normalized = []
        changed = False
        for value in cfg.user_groups or []:
            group_id = None
            if isinstance(value, int):
                group_id = value
            elif isinstance(value, str):
                key = value.strip()
                group_id = by_id.get(key) or by_name.get(key) or by_slug.get(key)
                changed = True
            else:
                changed = True

            if group_id is None:
                continue
            if group_id not in normalized:
                normalized.append(group_id)

        if changed or normalized != cfg.user_groups:
            cfg.user_groups = normalized
            cfg.save(update_fields=['user_groups'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0027_alter_notificationconfig_user_groups'),
        ('organization', '0007_remove_usergroup_organization_usergroup_slug_unique_and_more'),
    ]

    operations = [
        migrations.RunPython(normalize_user_groups, migrations.RunPython.noop),
    ]
