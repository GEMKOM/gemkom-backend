from django.db import migrations


PORTAL_PERMISSIONS = [
    ('office_access',   'Can log in to the office portal (ofis.gemcore.com.tr)'),
    ('workshop_access', 'Can log in to the workshop portal (saha.gemcore.com.tr)'),
]


def assign_portal_permissions(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')

    ct = ContentType.objects.get_for_model(UserProfile)

    # Create the two permissions if they don't exist yet
    for codename, name in PORTAL_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': name},
        )

    office_perm = Permission.objects.get(codename='office_access', content_type=ct)
    workshop_perm = Permission.objects.get(codename='workshop_access', content_type=ct)

    for profile in UserProfile.objects.select_related('user').all():
        if profile.work_location == 'office':
            profile.user.user_permissions.add(office_perm)
        else:
            profile.user.user_permissions.add(workshop_perm)


def remove_portal_permissions(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    UserProfile = apps.get_model('users', 'UserProfile')
    ct = ContentType.objects.get_for_model(UserProfile)
    Permission.objects.filter(
        codename__in=['office_access', 'workshop_access'],
        content_type=ct,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0024_userpermissionoverride'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(
            assign_portal_permissions,
            reverse_code=remove_portal_permissions,
        ),
    ]
