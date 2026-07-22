from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from projects.services.production_plan import (
    _compute_forecast,
    _effective_start_map,
    _job_order_forecast,
    _natural_job_key,
    _progress_from_domains,
    _visible_task_dicts,
)
from projects.services.schedule import (
    ZERO,
    add_working_days,
    next_working_day,
    span_end,
)

# July 2026: Wed 1, Thu 2, Fri 3, Sat 4, Sun 5, Mon 6, Tue 7, Wed 8, Thu 9,
# Fri 10, Sat 11, Sun 12, Mon 13, Tue 14, Wed 15, Thu 16, Fri 17
D = lambda day: date(2026, 7, day)
TODAY = D(8)  # Wednesday


def make_task(task_id, job='J-01', seq=1, parent=None, status='pending', pct=0.0,
              ts=None, te=None, astart=None, aend=None, deps=(), cls='not_started'):
    return {
        'id': task_id,
        'job_no': job,
        'parent': parent,
        'sequence': seq,
        'status': status,
        'completion_percentage': pct,
        'depends_on': list(deps),
        'target_start_date': ts,
        'target_completion_date': te,
        'schedule': {
            'actual_start_date': astart,
            'actual_end_date': aend,
            'start_variance_wd': None,
            'end_variance_wd': None,
            'overdue_wd': None,
            'classification': cls,
            'projected_start_date': None,
            'projected_end_date': None,
            'projected_variance_wd': None,
            'pushed_by': None,
        },
    }


class ScheduleWalkHelperTests(SimpleTestCase):
    def test_span_end_counts_start_day(self):
        # 1-workday task starting Monday ends Monday
        self.assertEqual(span_end(D(6), Decimal('1'), {}), D(6))
        # 2-workday task starting Friday ends Monday (weekend skipped)
        self.assertEqual(span_end(D(3), Decimal('2'), {}), D(6))

    def test_span_end_skips_holiday(self):
        calendar = {D(7): ZERO}  # Tuesday full holiday
        self.assertEqual(span_end(D(6), Decimal('2'), calendar), D(8))

    def test_add_working_days_excludes_start(self):
        self.assertEqual(add_working_days(D(8), Decimal('5'), {}), D(15))
        self.assertEqual(add_working_days(D(3), Decimal('1'), {}), D(6))  # Fri +1 -> Mon

    def test_next_working_day_over_weekend(self):
        self.assertEqual(next_working_day(D(3), {}), D(6))  # after Fri -> Mon


class ForecastProjectionTests(SimpleTestCase):
    def test_started_task_projects_from_work_rate(self):
        # Started Wed Jul 1, today Wed Jul 8 -> elapsed 5 wd; 50% done ->
        # remaining 5 wd -> projected end Wed Jul 15. Target Jul 10 -> +3 late.
        task = make_task(1, status='in_progress', pct=50.0, astart=D(1),
                         ts=D(1), te=D(10), cls='in_progress')
        _compute_forecast([task], TODAY, {})
        sched = task['schedule']
        self.assertEqual(sched['projected_end_date'], D(15))
        self.assertEqual(sched['projected_variance_wd'], 3.0)
        self.assertEqual(sched['classification'], 'at_risk')
        self.assertIsNone(sched['pushed_by'])

    def test_on_track_task_keeps_classification(self):
        # 80% done after 5 wd -> remaining 1.25 wd -> ends Fri Jul 10, target Jul 17.
        task = make_task(1, status='in_progress', pct=80.0, astart=D(1),
                         ts=D(1), te=D(17), cls='in_progress')
        _compute_forecast([task], TODAY, {})
        sched = task['schedule']
        self.assertEqual(sched['projected_end_date'], D(10))
        self.assertEqual(sched['classification'], 'in_progress')
        self.assertLess(sched['projected_variance_wd'], 0)

    def test_sequence_fallback_pushes_next_main(self):
        # A (seq 1) projects to Jul 15; B (seq 2, pending, planned Jul 9-10)
        # has no explicit deps -> pushed to start Thu Jul 16, 2-wd duration
        # ends Fri Jul 17 -> +5 vs its Jul 10 target.
        a = make_task(1, seq=1, status='in_progress', pct=50.0, astart=D(1),
                      ts=D(1), te=D(10), cls='in_progress')
        b = make_task(2, seq=2, status='pending', ts=D(9), te=D(10), cls='not_started')
        _compute_forecast([a, b], TODAY, {})
        sched = b['schedule']
        self.assertEqual(sched['projected_start_date'], D(16))
        self.assertEqual(sched['projected_end_date'], D(17))
        self.assertEqual(sched['pushed_by'], 1)
        self.assertEqual(sched['projected_variance_wd'], 5.0)
        self.assertEqual(sched['classification'], 'at_risk')

    def test_explicit_dependency_overrides_sequence(self):
        # C explicitly depends on A (not on B, its sequence predecessor).
        a = make_task(1, seq=1, status='in_progress', pct=50.0, astart=D(1),
                      ts=D(1), te=D(10), cls='in_progress')          # -> Jul 15
        b = make_task(2, seq=2, status='completed', aend=D(3), cls='completed_on_time')
        c = make_task(3, seq=3, status='pending', ts=D(9), te=D(10),
                      deps=(1,), cls='not_started')
        _compute_forecast([a, b, c], TODAY, {})
        self.assertEqual(c['schedule']['pushed_by'], 1)
        self.assertEqual(c['schedule']['projected_start_date'], D(16))

    def test_completed_predecessor_does_not_push(self):
        # Predecessor finished Fri Jul 3; clearance Mon Jul 6 < today -> the
        # successor starts on its own terms, no push.
        a = make_task(1, seq=1, status='completed', aend=D(3), cls='completed_on_time')
        b = make_task(2, seq=2, status='pending', ts=D(9), te=D(10), cls='not_started')
        _compute_forecast([a, b], TODAY, {})
        sched = b['schedule']
        self.assertIsNone(sched['pushed_by'])
        self.assertEqual(sched['projected_start_date'], D(9))
        self.assertEqual(sched['projected_end_date'], D(10))
        self.assertEqual(sched['classification'], 'not_started')

    def test_unplanned_task_gets_projection_but_keeps_classification(self):
        task = make_task(1, status='pending', cls='unplanned')
        _compute_forecast([task], TODAY, {})
        sched = task['schedule']
        self.assertEqual(sched['projected_end_date'], TODAY)  # 1-wd default from today
        self.assertIsNone(sched['projected_variance_wd'])
        self.assertEqual(sched['classification'], 'unplanned')

    def test_excluded_and_completed_are_untouched(self):
        skipped = make_task(1, status='skipped', cls='excluded')
        done = make_task(2, seq=2, status='completed', aend=D(6), cls='completed_on_time')
        _compute_forecast([skipped, done], TODAY, {})
        self.assertIsNone(skipped['schedule']['projected_end_date'])
        self.assertIsNone(done['schedule']['projected_end_date'])

    def test_dependency_cycle_does_not_crash(self):
        a = make_task(1, seq=1, deps=(2,), ts=D(9), te=D(10), cls='not_started')
        b = make_task(2, seq=2, deps=(1,), ts=D(9), te=D(10), cls='not_started')
        _compute_forecast([a, b], TODAY, {})
        self.assertIsNotNone(a['schedule']['projected_end_date'])
        self.assertIsNotNone(b['schedule']['projected_end_date'])

    def test_subtasks_not_sequence_chained(self):
        # A subtask (parent set) must not inherit the implicit main-task chain.
        main = make_task(1, seq=1, status='in_progress', pct=50.0, astart=D(1),
                         ts=D(1), te=D(10), cls='in_progress')      # -> Jul 15
        sub = make_task(2, seq=2, parent=1, status='pending',
                        ts=D(9), te=D(10), cls='not_started')
        _compute_forecast([main, sub], TODAY, {})
        self.assertIsNone(sub['schedule']['pushed_by'])
        self.assertEqual(sub['schedule']['projected_start_date'], D(9))


def make_model_task(task_id, job='J-01', parent=None, task_type=None,
                    title='', department='manufacturing'):
    return SimpleNamespace(
        id=task_id, job_order_id=job, parent_id=parent,
        task_type=task_type, title=title, department=department,
    )


class EffectiveStartTests(SimpleTestCase):
    """Gerçek Başlangıç = first real work evidence, never the auto-start stamp."""

    def test_domain_evidence_by_type_and_title(self):
        tasks = [
            make_model_task(1, task_type='machining'),
            make_model_task(2, title='CNC Kesim'),
            make_model_task(3, title='Kaynaklı İmalat'),
            make_model_task(4, department='procurement'),
            make_model_task(5, department='design'),
            make_model_task(6, department='logistics'),  # no evidence stream
        ]
        evidence = {
            'machining': {'J-01': D(10)},
            'cnc': {'J-01': D(9)},
            'welding': {'J-01': D(13)},
            'procurement': {'J-01': D(2)},
            'design': {'J-01': D(1)},
        }
        result = _effective_start_map(tasks, evidence)
        self.assertEqual(result[1], D(10))
        self.assertEqual(result[2], D(9))
        self.assertEqual(result[3], D(13))
        self.assertEqual(result[4], D(2))
        self.assertEqual(result[5], D(1))
        self.assertIsNone(result[6])

    def test_main_inherits_earliest_subtask_evidence(self):
        main = make_model_task(1, department='planning')          # no own stream
        sub_cnc = make_model_task(2, parent=1, title='CNC Kesim')
        sub_weld = make_model_task(3, parent=1, title='Kaynaklı İmalat')
        evidence = {'cnc': {'J-01': D(9)}, 'welding': {'J-01': D(6)}}
        result = _effective_start_map([main, sub_cnc, sub_weld], evidence)
        self.assertEqual(result[1], D(6))  # earliest child evidence

    def test_no_evidence_means_none_not_creation_date(self):
        main = make_model_task(1, department='planning')
        sub = make_model_task(2, parent=1, department='planning')
        result = _effective_start_map([main, sub], {})
        self.assertIsNone(result[1])
        self.assertIsNone(result[2])


def sched_task(task_id, status='pending', cls='not_started',
               projected_end=None, actual_end=None):
    td = make_task(task_id, status=status, cls=cls)
    td['schedule']['projected_end_date'] = projected_end
    td['schedule']['actual_end_date'] = actual_end
    return td


class JobOrderForecastTests(SimpleTestCase):
    """Job-level verdict: will the job order finish on time?"""

    def test_completed_job_on_time_and_late(self):
        on_time = _job_order_forecast('completed', D(9), D(10), [], {})
        self.assertEqual(on_time['verdict'], 'finished_on_time')
        late = _job_order_forecast('completed', D(15), D(10), [], {})
        self.assertEqual(late['verdict'], 'finished_late')
        self.assertEqual(late['variance_wd'], 3.0)  # Mon 13, Tue 14, Wed 15

    def test_open_job_late_risk_uses_latest_task_end(self):
        tasks = [
            sched_task(1, status='completed', cls='completed_on_time', actual_end=D(3)),
            sched_task(2, status='in_progress', cls='at_risk', projected_end=D(15)),
            sched_task(3, status='in_progress', cls='in_progress', projected_end=D(9)),
        ]
        fc = _job_order_forecast('active', None, D(10), tasks, {})
        self.assertEqual(fc['projected_completion_date'], D(15))
        self.assertEqual(fc['variance_wd'], 3.0)
        self.assertEqual(fc['verdict'], 'late_risk')

    def test_open_job_on_track(self):
        tasks = [sched_task(1, status='in_progress', cls='in_progress', projected_end=D(9))]
        fc = _job_order_forecast('active', None, D(10), tasks, {})
        self.assertEqual(fc['verdict'], 'on_track')
        self.assertLessEqual(fc['variance_wd'], 0)

    def test_excluded_tasks_ignored(self):
        tasks = [
            sched_task(1, status='in_progress', cls='in_progress', projected_end=D(9)),
            sched_task(2, status='cancelled', cls='excluded', projected_end=D(17)),
        ]
        fc = _job_order_forecast('active', None, D(10), tasks, {})
        self.assertEqual(fc['projected_completion_date'], D(9))
        self.assertEqual(fc['verdict'], 'on_track')

    def test_no_target_and_unknown(self):
        tasks = [sched_task(1, status='in_progress', cls='in_progress', projected_end=D(15))]
        no_target = _job_order_forecast('active', None, None, tasks, {})
        self.assertEqual(no_target['verdict'], 'no_target')
        self.assertEqual(no_target['projected_completion_date'], D(15))
        unknown = _job_order_forecast('active', None, D(10), [], {})
        self.assertEqual(unknown['verdict'], 'unknown')

    def test_unplanned_open_counter(self):
        tasks = [
            sched_task(1, status='pending', cls='unplanned', projected_end=D(9)),
            sched_task(2, status='completed', cls='unplanned', actual_end=D(3)),
            sched_task(3, status='in_progress', cls='in_progress', projected_end=D(9)),
        ]
        fc = _job_order_forecast('active', None, D(10), tasks, {})
        self.assertEqual(fc['unplanned_open_tasks'], 1)  # only the OPEN unplanned one


class _StubManager:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return self._items


def special_task(job='J-01', task_type=None, title='', department='manufacturing',
                 status='in_progress', manual=0, subtasks=()):
    return SimpleNamespace(
        job_order_id=job, task_type=task_type, title=title, department=department,
        status=status, manual_progress=Decimal(str(manual)),
        subtasks=_StubManager(subtasks),
    )


class BatchedProgressTests(SimpleTestCase):
    """_progress_from_domains mirrors get_completion_percentage's special branches."""

    def test_cnc_and_machining_ratio_capped_at_99(self):
        domains = {'cnc': {'J-01': (Decimal('100'), Decimal('100'))},
                   'machining': {'J-01': (Decimal('30'), Decimal('40'))},
                   'procurement': {}}
        self.assertEqual(
            _progress_from_domains(special_task(task_type='cnc_cutting'), domains, {}),
            Decimal('99.00'))  # 100% earned but open -> capped
        self.assertEqual(
            _progress_from_domains(special_task(title='Talaşlı İmalat'), domains, {}),
            Decimal('75.00'))

    def test_cnc_without_parts_is_zero(self):
        domains = {'cnc': {}, 'machining': {}, 'procurement': {}}
        self.assertEqual(
            _progress_from_domains(special_task(task_type='cnc_cutting'), domains, {}),
            Decimal('0.00'))

    def test_procurement_without_items_falls_through_to_manual(self):
        domains = {'cnc': {}, 'machining': {}, 'procurement': {}}
        task = special_task(department='procurement', status='in_progress', manual=35)
        self.assertEqual(_progress_from_domains(task, domains, {}), Decimal('35'))
        # pending falls to zero, like the generic branch
        pending = special_task(department='procurement', status='pending', manual=35)
        self.assertEqual(_progress_from_domains(pending, domains, {}), Decimal('0.00'))

    def test_procurement_with_items_uses_ratio_even_when_pending(self):
        domains = {'cnc': {}, 'machining': {},
                   'procurement': {'J-01': (Decimal('40'), Decimal('100'))}}
        pending = special_task(department='procurement', status='pending')
        self.assertEqual(_progress_from_domains(pending, domains, {}), Decimal('40.00'))

    def test_procurement_fallthrough_weights_subtasks_full_path(self):
        # No purchaseable items + subtasks: weight-weighted with partial
        # credit, cancelled subtasks excluded (models.py full path, not the
        # count-based skip path).
        domains = {'cnc': {}, 'machining': {}, 'procurement': {}}
        subs = [
            SimpleNamespace(id=11, status='completed', weight=30),
            SimpleNamespace(id=12, status='in_progress', weight=10),
            SimpleNamespace(id=13, status='cancelled', weight=100),  # excluded
        ]
        task = special_task(department='procurement', status='in_progress', subtasks=subs)
        progress = {11: Decimal('100.00'), 12: Decimal('40.00')}
        # (100*30 + 40*10) / 40 = 85
        self.assertEqual(_progress_from_domains(task, domains, progress), Decimal('85.00'))


class OverviewHelperTests(SimpleTestCase):
    def test_natural_job_key_ordering(self):
        jobs = ['295-02', '295-01', '097-42', 'RM262-01', '9-1', '295-10']
        ordered = sorted(jobs, key=_natural_job_key)
        self.assertEqual(ordered, ['9-1', '097-42', '295-01', '295-02', '295-10', 'RM262-01'])

    def test_visible_task_dicts_hides_parents_with_children(self):
        dicts = [
            {'id': 1, 'parent': None},
            {'id': 2, 'parent': 1},
            {'id': 3, 'parent': None},   # childless main stays
        ]
        visible = _visible_task_dicts(dicts)
        self.assertEqual([td['id'] for td in visible], [2, 3])
