from django.db import migrations


def fix_rolling_mill_subject_type(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    # Haddehane Onayı was purchase_request with is_rolling_mill=True — give it its own subject type
    ApprovalPolicy.objects.filter(
        subject_type='purchase_request',
        is_rolling_mill=True,
    ).update(subject_type='purchase_request_rolling_mill')


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0011_approvalpolicy_subject_type'),
    ]

    operations = [
        migrations.RunPython(fix_rolling_mill_subject_type, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='approvalpolicy',
            name='is_rolling_mill',
        ),
    ]
