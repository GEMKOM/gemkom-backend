from projects.models import DepartmentTaskTemplateItem, JobOrderDepartmentTask

TITLE_TO_TYPE = {
    'Kaynaklı İmalat': 'welding',
    'Talaşlı İmalat': 'machining',
    'Boya':            'painting',
    'CNC Kesim':       'cnc_cutting',
}

# --- Fix template items ---
template_total = 0
for title, task_type in TITLE_TO_TYPE.items():
    updated = DepartmentTaskTemplateItem.objects.filter(
        title=title,
        task_type__isnull=True
    ).update(task_type=task_type)
    if updated:
        print(f"[Template] '{title}' → {task_type}: {updated} row(s)")
    template_total += updated

print(f"[Template] Total updated: {template_total}")

# --- Fix job order tasks ---
task_total = 0
for title, task_type in TITLE_TO_TYPE.items():
    updated = JobOrderDepartmentTask.objects.filter(
        title=title,
        task_type__isnull=True
    ).update(task_type=task_type)
    if updated:
        print(f"[Task]     '{title}' → {task_type}: {updated} row(s)")
    task_total += updated

print(f"[Task]     Total updated: {task_total}")
print("Done.")
