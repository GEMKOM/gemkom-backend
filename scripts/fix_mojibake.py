# -*- coding: utf-8 -*-
from projects.models import JobOrderDepartmentTask

BAD_TITLE = 'KaynaklÄ± Ä°malat'
GOOD_TITLE = 'Kaynaklı İmalat'

qs = JobOrderDepartmentTask.objects.filter(title=BAD_TITLE)
count = qs.count()
print(f"Found {count} records to fix.")
qs.update(title=GOOD_TITLE)
print("Done.")
