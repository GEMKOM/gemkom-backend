from projects.models import JobOrderDepartmentTask

c1 = JobOrderDepartmentTask.objects.filter(title__contains='Kaynakl', task_type__isnull=True).update(task_type='welding')
print(f"Welding updated: {c1}")
c2 = JobOrderDepartmentTask.objects.filter(title__contains='Tala', task_type__isnull=True).update(task_type='machining')
print(f"Machining updated: {c2}")
