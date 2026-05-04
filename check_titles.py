from projects.models import DepartmentTaskTemplateItem, JobOrderDepartmentTask

print("=== Template items with null task_type ===")
for item in DepartmentTaskTemplateItem.objects.filter(task_type__isnull=True):
    print(repr(item.title))

print("\n=== Job order tasks with null task_type (distinct titles) ===")
titles = JobOrderDepartmentTask.objects.filter(task_type__isnull=True).values_list('title', flat=True).distinct()
for t in titles:
    print(repr(t))
