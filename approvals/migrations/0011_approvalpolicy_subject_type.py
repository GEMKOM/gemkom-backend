from django.db import migrations, models


SUBJECT_MAP = {
    "Vacation – Default":              "vacation_request",
    "Overtime – Default":              "overtime_request",
    "Department Request – Default":    "department_request",
    "Default Policy":                  "purchase_request",
    "Haddehane Onayı":                 "purchase_request",
    "taseron":                         "subcontractor_statement",
    "KK İnceleme Onay Politikası":     "qc_review",
    "NCR Onay Politikası":             "ncr",
    "Satış Teklif Onayı":              "sales_offer",
}


def populate_subject_type(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    for policy in ApprovalPolicy.objects.all():
        subject = SUBJECT_MAP.get(policy.name, '')
        if subject:
            policy.subject_type = subject
            policy.save(update_fields=['subject_type'])


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0010_set_stage_rules'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvalpolicy',
            name='subject_type',
            field=models.SlugField(
                blank=True,
                default='',
                help_text='Which workflow subject this policy applies to. Used for policy lookup; renaming the policy will not break routing.',
            ),
        ),
        migrations.RunPython(populate_subject_type, migrations.RunPython.noop),
    ]
