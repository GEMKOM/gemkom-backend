from projects.models import DepartmentTaskTemplateItem, JobOrderDepartmentTask

pairs = [
    ('Kaynakl', 'welding'),
    ('Tala', 'machining'),
]

for fragment, task_type in pairs:
    qs = DepartmentTaskTemplateItem.objects.filter(title__contains=fragment)
    print(f"Template: found {qs.count()} with fragment '{fragment}'")
    for item in qs:
        print(f"  id={item.id} title={repr(item.title)} task_type={repr(item.task_type)}")
    updated = qs.filter(task_type__isnull=True).update(task_type=task_type)
    print(f"  Updated {updated} template row(s) to {task_type}")

    qs2 = JobOrderDepartmentTask.objects.filter(title__contains=fragment, task_type__isnull=True)
    updated2 = qs2.update(task_type=task_type)
    print(f"  Updated {updated2} job order task(s) to {task_type}")
