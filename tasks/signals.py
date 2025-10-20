from django.db.models.signals import post_delete
from django.dispatch import receiver
from tasks.models import TaskFile



@receiver(post_delete, sender=TaskFile)
def delete_file_on_taskfile_delete(sender, instance, **kwargs):
    """
    Deletes the actual file from storage when a TaskFile object is deleted.
    """
    if instance.file:
        instance.file.delete(save=False)