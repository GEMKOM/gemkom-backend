from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='users.UserProfile')
def sync_permissions_on_profile_save(sender, instance, **kwargs):
    """
    Sync user.user_permissions whenever UserProfile.position changes.
    Runs on every full save; for update_fields saves, only runs if
    position_id is in the updated fields.
    """
    update_fields = kwargs.get('update_fields')
    if update_fields is not None:
        touched = set(update_fields)
        if 'position_id' not in touched and 'position' not in touched:
            return

    from .services import sync_user_permissions
    sync_user_permissions(instance.user, instance.position)
