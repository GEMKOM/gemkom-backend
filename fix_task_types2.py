from projects.models import DepartmentTaskTemplateItem, JobOrderDepartmentTask

TITLE_TO_TYPE = {
    'Kaynaklı İmalat': 'welding',
    'Talaşlı İmalat': 'machining',
}

for title, task_type in TITLE_TO_TYPE.items():
    qs = DepartmentTaskTemplateItem.objects.filter(title=title)
    print(f"Found {qs.count()} template item(s) with title {repr(title)}")
    for item in qs:
        print(f"  id={item.id} task_type={repr(item.task_type)}")
    updated = qs.filter(task_type__isnull=True).update(task_type=task_type)
    print(f"  Updated {updated} row(s) to {task_type}")

    qs2 = JobOrderDepartmentTask.objects.filter(title=title, task_type__isnull=True)
    updated2 = qs2.update(task_type=task_type)
    print(f"  Updated {updated2} job order task(s) to {task_type}")
