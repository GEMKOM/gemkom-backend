"""Helpers for shared storage keys across TaskFile and planning.FileAsset."""


def is_storage_key_referenced(file_name, *, exclude_taskfile_id=None, exclude_fileasset_id=None):
    """Return True if another row still points at the same storage key."""
    if not file_name:
        return False

    from planning.models import FileAsset
    from tasks.models import TaskFile

    task_qs = TaskFile.objects.filter(file=file_name)
    if exclude_taskfile_id is not None:
        task_qs = task_qs.exclude(pk=exclude_taskfile_id)
    if task_qs.exists():
        return True

    asset_qs = FileAsset.objects.filter(file=file_name)
    if exclude_fileasset_id is not None:
        asset_qs = asset_qs.exclude(pk=exclude_fileasset_id)
    return asset_qs.exists()


def safe_delete_storage_file(file_field, *, exclude_taskfile_id=None, exclude_fileasset_id=None):
    """Delete the physical file only when no other row references the same key."""
    if not file_field:
        return
    if is_storage_key_referenced(
        file_field.name,
        exclude_taskfile_id=exclude_taskfile_id,
        exclude_fileasset_id=exclude_fileasset_id,
    ):
        return
    file_field.delete(save=False)
