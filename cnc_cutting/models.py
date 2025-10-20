from django.db import models
from tasks.models import BaseTask
from django.contrib.contenttypes.fields import GenericRelation


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

    # This creates the reverse relationship from a CncTask back to all its Timers.
    # It allows `prefetch_related('issue_key')` to work on CncTask querysets.
    issue_key = GenericRelation(
        'tasks.Timer',
        content_type_field='content_type',
        object_id_field='object_id',
    )

    # Add any other fields you need for CNC tasks.
    def __str__(self):
        return f"CncTask {self.key} - {self.nesting_id or 'No Nesting ID'}"


class CncPart(models.Model):
    """
    Represents a single part within a CncTask nesting.
    This allows tracking the status and properties of individual components
    cut from a single plate.
    """
    cnc_task = models.ForeignKey(CncTask, on_delete=models.CASCADE, related_name='parts', help_text="The nesting task this part belongs to.")

    # --- Part Identifiers ---
    # These fields link the cut part to a specific job or component identifier.
    job_no = models.CharField(max_length=255, db_index=True)
    image_no = models.CharField(max_length=255, blank=True, null=True)
    position_no = models.CharField(max_length=255, blank=True, null=True)

    # --- Costing ---
    weight_kg = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, help_text="Weight of the single part in kg.")

    def __str__(self):
        return f"Part for Job {self.job_no} (Pos: {self.position_no or 'N/A'}) in Nest {self.cnc_task.key}"
