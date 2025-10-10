from django.db import models
from tasks.models import BaseTask
from core.storages import PrivateMediaStorage
import os

def cnc_task_file_upload_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/task_files/cnc_tasks/<task_id>/<filename>
    # or directly to the bucket if using S3 storage
    return os.path.join('cnc_tasks', str(instance.key), filename)

class CncTask(BaseTask):
    """
    A CNC-specific task. Inherits common fields from BaseTask
    and adds fields unique to CNC cutting.
    """
    # Example CNC-specific fields:
    nesting_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    material = models.CharField(max_length=100, null=True, blank=True)
    dimensions = models.CharField(max_length=100, null=True, blank=True)
    thickness_mm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    nesting_pdf = models.FileField(upload_to=cnc_task_file_upload_path, storage=PrivateMediaStorage(), null=True, blank=True, verbose_name="Nesting PDF")

    # Add any other fields you need for CNC tasks.
    def __str__(self):
        return f"CncTask {self.key} - {self.nesting_id or 'No Nesting ID'}"
