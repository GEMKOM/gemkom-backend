"""
Migration 0014: Introduce AttendanceSession and refactor AttendanceRecord.

Steps:
1. Create AttendanceSession table.
2. Data migration: for every AttendanceRecord that has a check_in_time, create
   an AttendanceSession row preserving all timing, method, status, IP, and
   coordinate data.
3. Add new daily-aggregate fields to AttendanceRecord
   (total_present_minutes; late/early/overtime already exist).
4. Remove fields that moved to AttendanceSession from AttendanceRecord:
   check_in_time, check_out_time, method, check_in_lat, check_in_lon,
   check_out_lat, check_out_lon, client_ip, override_reason.
5. Update AttendanceRecord ordering (no longer sorts by check_in_time).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


# ---------------------------------------------------------------------------
# Session status / method mapping from old record fields
# ---------------------------------------------------------------------------

def _session_status(record_status):
    """Map an old AttendanceRecord status to an AttendanceSession status."""
    mapping = {
        'active':                   'open',
        'complete':                 'closed',
        'pending_override':         'pending_override',
        'pending_checkout_override':'pending_checkout_override',
        'override_rejected':        'override_rejected',
        # leave records have no sessions — handled by the caller
    }
    return mapping.get(record_status, 'closed')


def migrate_records_to_sessions(apps, schema_editor):
    AttendanceRecord = apps.get_model('attendance', 'AttendanceRecord')
    AttendanceSession = apps.get_model('attendance', 'AttendanceSession')

    sessions_to_create = []
    for record in AttendanceRecord.objects.exclude(
        check_in_time__isnull=True
    ).exclude(status='leave'):
        session_status = _session_status(record.status)
        sessions_to_create.append(AttendanceSession(
            record=record,
            check_in_time=record.check_in_time,
            check_out_time=record.check_out_time,
            method=record.method,
            status=session_status,
            check_in_lat=record.check_in_lat,
            check_in_lon=record.check_in_lon,
            check_out_lat=record.check_out_lat,
            check_out_lon=record.check_out_lon,
            client_ip=record.client_ip,
            override_reason=record.override_reason,
        ))

    AttendanceSession.objects.bulk_create(sessions_to_create)

    # Populate total_present_minutes for records that are now complete
    for record in AttendanceRecord.objects.filter(status='complete'):
        total = 0
        for s in AttendanceSession.objects.filter(
            record=record, check_out_time__isnull=False
        ):
            delta = s.check_out_time - s.check_in_time
            total += max(0, int(delta.total_seconds() // 60))
        if total:
            record.total_present_minutes = total
            record.save(update_fields=['total_present_minutes'])


def reverse_migrate(apps, schema_editor):
    """Restore check_in/out times from the first session on each record."""
    AttendanceRecord = apps.get_model('attendance', 'AttendanceRecord')
    AttendanceSession = apps.get_model('attendance', 'AttendanceSession')

    for record in AttendanceRecord.objects.all():
        session = AttendanceSession.objects.filter(record=record).order_by('check_in_time').first()
        if session:
            record.check_in_time = session.check_in_time
            record.check_out_time = session.check_out_time
            record.method = session.method
            record.check_in_lat = session.check_in_lat
            record.check_in_lon = session.check_in_lon
            record.check_out_lat = session.check_out_lat
            record.check_out_lon = session.check_out_lon
            record.client_ip = session.client_ip
            record.override_reason = session.override_reason
            record.save(update_fields=[
                'check_in_time', 'check_out_time', 'method',
                'check_in_lat', 'check_in_lon', 'check_out_lat', 'check_out_lon',
                'client_ip', 'override_reason',
            ])


class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0013_add_is_half_day_to_publicholiday'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Create AttendanceSession
        migrations.CreateModel(
            name='AttendanceSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('check_in_time', models.DateTimeField()),
                ('check_out_time', models.DateTimeField(blank=True, null=True)),
                ('method', models.CharField(
                    choices=[
                        ('ip', 'IP (Ofis Ağı)'),
                        ('gps', 'GPS'),
                        ('manual_override', 'Manuel Değişim Talebi'),
                        ('hr_manual', 'HR Değişikliği'),
                    ],
                    max_length=20,
                )),
                ('status', models.CharField(
                    choices=[
                        ('open', 'Açık (Ofiste)'),
                        ('closed', 'Kapalı (Çıkış Yapıldı)'),
                        ('pending_override', 'HR Onayı Bekliyor (Giriş)'),
                        ('pending_checkout_override', 'HR Onayı Bekliyor (Çıkış)'),
                        ('override_rejected', 'Reddedildi'),
                    ],
                    default='open',
                    max_length=30,
                )),
                ('check_in_lat', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ('check_in_lon', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ('check_out_lat', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ('check_out_lon', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ('client_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('override_reason', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('record', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sessions',
                    to='attendance.attendancerecord',
                )),
            ],
            options={
                'verbose_name': 'Attendance Session',
                'verbose_name_plural': 'Attendance Sessions',
                'ordering': ['check_in_time'],
            },
        ),

        # 2. Add total_present_minutes to AttendanceRecord
        migrations.AddField(
            model_name='attendancerecord',
            name='total_present_minutes',
            field=models.IntegerField(
                default=0,
                help_text='Sum of all closed session durations for the day.',
            ),
        ),

        # 3. Data migration — copy timing data into sessions
        migrations.RunPython(migrate_records_to_sessions, reverse_migrate),

        # 4. Remove fields that moved to AttendanceSession
        migrations.RemoveField(model_name='attendancerecord', name='check_in_time'),
        migrations.RemoveField(model_name='attendancerecord', name='check_out_time'),
        migrations.RemoveField(model_name='attendancerecord', name='method'),
        migrations.RemoveField(model_name='attendancerecord', name='check_in_lat'),
        migrations.RemoveField(model_name='attendancerecord', name='check_in_lon'),
        migrations.RemoveField(model_name='attendancerecord', name='check_out_lat'),
        migrations.RemoveField(model_name='attendancerecord', name='check_out_lon'),
        migrations.RemoveField(model_name='attendancerecord', name='client_ip'),
        migrations.RemoveField(model_name='attendancerecord', name='override_reason'),

        # 5. Fix ordering on AttendanceRecord (was ['-date', '-check_in_time'])
        migrations.AlterModelOptions(
            name='attendancerecord',
            options={
                'ordering': ['-date'],
                'verbose_name': 'Attendance Record',
                'verbose_name_plural': 'Attendance Records',
            },
        ),
    ]
