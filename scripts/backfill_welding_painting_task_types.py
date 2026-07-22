# -*- coding: utf-8 -*-
"""
Data backfill: set task_type on existing DepartmentTaskTemplateItem and
JobOrderDepartmentTask rows from their titles.

    'Kaynaklı İmalat' -> 'welding'
    'Boya'            -> 'painting'

Only rows with task_type IS NULL are touched. Matching is exact on the
trimmed, casefolded title (not substring), so e.g. 'Boya Kabini' is skipped.
Near-miss titles containing 'kaynak'/'boya' are reported but NOT updated.

Run with:
    python manage.py shell -c "exec(open('scripts/backfill_welding_painting_task_types.py', encoding='utf-8').read())"
"""

import unicodedata

from projects.models import DepartmentTaskTemplateItem, JobOrderDepartmentTask

TITLE_TO_TYPE = {
    'kaynaklı imalat': 'welding',
    'boya': 'painting',
}

NEAR_MISS_KEYWORDS = ('kaynak', 'boya')


def normalize(title):
    # Turkish-aware lowercase: İ->i and I->ı BEFORE casefold, otherwise
    # 'İ'.casefold() yields 'i' + combining dot and never matches plain 'i'.
    t = unicodedata.normalize('NFC', (title or '').strip())
    t = t.replace('İ', 'i').replace('I', 'ı')
    return t.casefold()


def backfill(model, label):
    to_update = {}   # task_type -> [pks]
    near_misses = {}  # title -> count

    for pk, title in model.objects.filter(task_type__isnull=True).values_list('pk', 'title'):
        norm = normalize(title)
        task_type = TITLE_TO_TYPE.get(norm)
        if task_type:
            to_update.setdefault(task_type, []).append(pk)
        elif any(kw in norm for kw in NEAR_MISS_KEYWORDS):
            near_misses[title] = near_misses.get(title, 0) + 1

    total = 0
    for task_type, pks in to_update.items():
        updated = model.objects.filter(pk__in=pks, task_type__isnull=True).update(task_type=task_type)
        print(f"[{label}] -> {task_type}: {updated} row(s)")
        total += updated
    if not to_update:
        print(f"[{label}] nothing to update")

    if near_misses:
        print(f"[{label}] near-miss titles left untouched:")
        for title, count in sorted(near_misses.items()):
            print(f"    {ascii(title)}: {count} row(s)")

    return total


print("=== Template items ===")
template_total = backfill(DepartmentTaskTemplateItem, 'Template')

print("\n=== Job order tasks ===")
task_total = backfill(JobOrderDepartmentTask, 'Task')

print(f"\nDone. Template items updated: {template_total}, tasks updated: {task_total}")
