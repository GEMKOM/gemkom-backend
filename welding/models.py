from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class WeldingTimeEntry(models.Model):
    """
    Manual time entry for welding employees.
    Each entry represents hours worked by an employee on a specific job_no for a specific date.
    """
    OVERTIME_TYPE_CHOICES = [
        ('regular', 'Regular Hours'),
        ('after_hours', 'After Hours / Saturday (1.5x)'),
        ('holiday', 'Holiday / Sunday (2x)'),
    ]

    employee = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='welding_time_entries',
        db_index=True,
        help_text="The welding employee who worked on this job"
    )
    job_no = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Job number (e.g., '001-23'). Indexed for fast partial searches."
    )
    date = models.DateField(
        db_index=True,
        help_text="The date when the work was performed"
    )
    hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Number of hours worked (e.g., 2.5 for 2 hours 30 minutes)"
    )
    overtime_type = models.CharField(
        max_length=20,
        choices=OVERTIME_TYPE_CHOICES,
        default='regular',
        db_index=True,
        help_text="Type of work hours: regular, after_hours (1.5x), or holiday (2x)"
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Optional notes about the work performed"
    )

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_welding_entries'
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_welding_entries'
    )

    class Meta:
        db_table = 'welding_time_entry'
        ordering = ['-date', 'employee']
        indexes = [
            models.Index(fields=['employee', 'date']),
            models.Index(fields=['job_no', 'date']),
            models.Index(fields=['date']),
            models.Index(fields=['overtime_type']),
        ]
        verbose_name = 'Welding Time Entry'
        verbose_name_plural = 'Welding Time Entries'

    def __str__(self):
        overtime_display = dict(self.OVERTIME_TYPE_CHOICES).get(self.overtime_type, self.overtime_type)
        return f"{self.employee.username} - {self.job_no} - {self.date} ({self.hours}h - {overtime_display})"

    @property
    def overtime_multiplier(self):
        """Return the pay multiplier for this entry's overtime type."""
        multipliers = {
            'regular': 1.0,
            'after_hours': 1.5,
            'holiday': 2.0,
        }
        return multipliers.get(self.overtime_type, 1.0)
