from django.db import models
from tasks.models import BaseTask

class CncTask(BaseTask):
    """
    A CNC-specific task. Inherits common fields from BaseTask
    and adds fields unique to CNC cutting.
    """
    # Example CNC-specific fields:
    nesting_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    material = models.CharField(max_length=100, null=True, blank=True)
    thickness_mm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    # Add any other fields you need for CNC tasks.

