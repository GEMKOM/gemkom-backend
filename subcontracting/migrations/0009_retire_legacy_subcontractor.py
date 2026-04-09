from django.db import migrations


def retire_legacy_assignments(apps, schema_editor):
    SubcontractingAssignment = apps.get_model('subcontracting', 'SubcontractingAssignment')
    Subcontractor = apps.get_model('subcontracting', 'Subcontractor')
    legacy = Subcontractor.objects.filter(name='Eski Taşeron (Devir)').first()
    if legacy:
        SubcontractingAssignment.objects.filter(subcontractor=legacy).update(is_retired=True)


class Migration(migrations.Migration):

    dependencies = [
        ('subcontracting', '0008_backfill_subtask_weight_from_allocated_kg'),
    ]

    operations = [
        migrations.RunPython(retire_legacy_assignments, migrations.RunPython.noop),
    ]
