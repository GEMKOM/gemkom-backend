from django.db import migrations


DEFAULT_CODENAMES = ['add_userprofile', 'change_userprofile', 'delete_userprofile', 'view_userprofile']


def remove_default_perms(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.filter(codename__in=DEFAULT_CODENAMES, content_type=ct).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0028_workshop_page_permissions'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(remove_default_perms, reverse_code=migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name='userprofile',
            options={'default_permissions': ()},
        ),
    ]
