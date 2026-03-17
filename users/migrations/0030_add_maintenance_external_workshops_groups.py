from django.db import migrations


def add_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name='maintenance_team')
    # Remove external_workshops_team if it was previously created
    Group.objects.filter(name='external_workshops_team').delete()


def remove_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='maintenance_team').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0029_remove_default_userprofile_permissions'),
    ]

    operations = [
        migrations.RunPython(add_groups, reverse_code=remove_groups),
    ]
