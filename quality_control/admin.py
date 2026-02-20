from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from .models import QCReview, NCR


# =============================================================================
# NCR inline — shown inside QCReview change page
# =============================================================================

class NCRInline(admin.TabularInline):
    model = NCR
    fk_name = 'qc_review'
    extra = 0
    fields = ('ncr_number', 'title', 'severity', 'status', 'disposition', 'submission_count')
    readonly_fields = ('ncr_number', 'submission_count')
    show_change_link = True
    can_delete = True


# =============================================================================
# QCReview admin
# =============================================================================

@admin.register(QCReview)
class QCReviewAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'task_link', 'job_order', 'status',
        'submitted_by', 'submitted_at',
        'reviewed_by', 'reviewed_at',
        'ncr_link',
    )
    list_filter = ('status', 'task__department', 'task__job_order')
    search_fields = (
        'task__title', 'task__job_order__job_no',
        'submitted_by__first_name', 'submitted_by__last_name',
    )
    date_hierarchy = 'submitted_at'
    ordering = ('-submitted_at',)
    readonly_fields = ('submitted_at', 'reviewed_at')
    raw_id_fields = ('task', 'submitted_by', 'reviewed_by', 'ncr')
    inlines = [NCRInline]

    @admin.display(description='Task')
    def task_link(self, obj):
        try:
            url = reverse('admin:projects_joborderdepartmenttask_change', args=[obj.task_id])
            return format_html('<a href="{}">{}</a>', url, obj.task)
        except Exception:
            return str(obj.task)

    @admin.display(description='Job Order')
    def job_order(self, obj):
        return obj.task.job_order_id

    @admin.display(description='NCR')
    def ncr_link(self, obj):
        if not obj.ncr_id:
            return '-'
        try:
            url = reverse('admin:quality_control_ncr_change', args=[obj.ncr_id])
            return format_html('<a href="{}">{}</a>', url, obj.ncr)
        except Exception:
            return str(obj.ncr)

    def delete_queryset(self, request, queryset):
        """
        Override bulk delete to run per-object delete so that the cascade
        logic (unblocking tasks) fires correctly via model delete signals / DB cascade.
        """
        for obj in queryset:
            obj.delete()

    def delete_model(self, request, obj):
        """
        When a QCReview is deleted:
        - Its NCRs are cascade-deleted (SET_NULL on qc_review FK → we handle manually)
        - The linked task is unblocked if it was blocked because of this review
        """
        task = obj.task
        was_blocked_by_this_review = (
            task.status == 'blocked'
            and not QCReview.objects.filter(task=task, status='rejected').exclude(pk=obj.pk).exists()
        )

        obj.delete()  # cascades NCRs via DB (department_task FK on NCR is SET_NULL, qc_review FK is SET_NULL)

        if was_blocked_by_this_review:
            task.refresh_from_db()
            if task.status == 'blocked':
                task.status = 'in_progress'
                task.save(update_fields=['status'])


# =============================================================================
# NCR admin
# =============================================================================

@admin.register(NCR)
class NCRAdmin(admin.ModelAdmin):
    list_display = (
        'ncr_number', 'title',
        'job_order', 'department_task_link',
        'severity', 'defect_type', 'status',
        'disposition', 'submission_count',
        'assigned_team',
        'created_by', 'created_at',
    )
    list_filter = ('status', 'severity', 'defect_type', 'assigned_team', 'disposition')
    search_fields = (
        'ncr_number', 'title', 'description',
        'job_order__job_no',
        'created_by__first_name', 'created_by__last_name',
    )
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('ncr_number', 'submission_count', 'created_at', 'updated_at')
    raw_id_fields = ('job_order', 'department_task', 'qc_review', 'detected_by', 'created_by')
    filter_horizontal = ('assigned_members',)
    fieldsets = (
        ('Identification', {
            'fields': ('ncr_number', 'title', 'description'),
        }),
        ('Links', {
            'fields': ('job_order', 'department_task', 'qc_review'),
        }),
        ('Classification', {
            'fields': ('defect_type', 'severity', 'affected_quantity', 'detected_by'),
        }),
        ('Resolution', {
            'fields': ('root_cause', 'corrective_action', 'disposition'),
        }),
        ('Assignment', {
            'fields': ('assigned_team', 'assigned_members'),
        }),
        ('Status', {
            'fields': ('status', 'submission_count'),
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
        }),
    )

    @admin.display(description='Department Task')
    def department_task_link(self, obj):
        if not obj.department_task_id:
            return '-'
        try:
            url = reverse('admin:projects_joborderdepartmenttask_change', args=[obj.department_task_id])
            return format_html('<a href="{}">{}</a>', url, obj.department_task)
        except Exception:
            return str(obj.department_task)

    def delete_model(self, request, obj):
        """
        When an NCR is deleted, unblock the linked task if it was
        blocked solely because of the QCReview that created this NCR.
        """
        task = obj.department_task
        obj.delete()

        if task and task.status == 'blocked':
            # Unblock only if no other rejected (open) QCReview remains
            has_open_rejection = task.qc_reviews.filter(status='rejected').filter(
                ncr__isnull=True
            ).exists() or task.qc_reviews.filter(status='rejected', ncr__status__in=['draft', 'submitted']).exists()
            if not has_open_rejection:
                task.status = 'in_progress'
                task.save(update_fields=['status'])

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            obj.delete()
