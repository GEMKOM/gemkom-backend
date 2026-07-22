from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.test import SimpleTestCase

from projects.services.production_plan import _classify
from projects.services.schedule import (
    HALF,
    ZERO,
    day_value,
    local_date,
    working_day_delta,
)

# July 2026: Wed 1, Thu 2, Fri 3, Sat 4, Sun 5, Mon 6, Tue 7, Wed 8, ... Fri 10
FRI = date(2026, 7, 3)
SAT = date(2026, 7, 4)
SUN = date(2026, 7, 5)
MON = date(2026, 7, 6)
TUE = date(2026, 7, 7)
WED = date(2026, 7, 8)
NEXT_FRI = date(2026, 7, 10)


class WorkingDayDeltaTests(SimpleTestCase):
    """Signed working-day lateness over a half-open (planned, actual] interval."""

    def test_same_day_is_on_time(self):
        self.assertEqual(working_day_delta(FRI, FRI, {}), Decimal('0'))

    def test_friday_target_weekend_actual_is_on_time(self):
        self.assertEqual(working_day_delta(FRI, SAT, {}), Decimal('0'))
        self.assertEqual(working_day_delta(FRI, SUN, {}), Decimal('0'))

    def test_friday_target_monday_actual_is_one_day_late(self):
        self.assertEqual(working_day_delta(FRI, MON, {}), Decimal('1'))

    def test_full_week_is_five_working_days(self):
        self.assertEqual(working_day_delta(FRI, NEXT_FRI, {}), Decimal('5'))

    def test_full_holiday_not_counted(self):
        calendar = {TUE: ZERO}  # Tuesday is a full public holiday
        self.assertEqual(working_day_delta(MON, WED, calendar), Decimal('1'))

    def test_half_day_holiday_counts_half(self):
        calendar = {TUE: HALF}  # Tuesday is an Arife
        self.assertEqual(working_day_delta(MON, TUE, calendar), Decimal('0.5'))

    def test_early_completion_is_negative(self):
        self.assertEqual(working_day_delta(MON, FRI, {}), Decimal('-1'))
        self.assertEqual(working_day_delta(NEXT_FRI, FRI, {}), Decimal('-5'))

    def test_missing_dates_return_none(self):
        self.assertIsNone(working_day_delta(None, FRI, {}))
        self.assertIsNone(working_day_delta(FRI, None, {}))


class DayValueTests(SimpleTestCase):
    def test_weekend_is_zero_even_if_not_in_calendar(self):
        self.assertEqual(day_value(SAT, {}), ZERO)
        self.assertEqual(day_value(SUN, {}), ZERO)

    def test_weekday_values(self):
        self.assertEqual(day_value(MON, {}), Decimal('1'))
        self.assertEqual(day_value(MON, {MON: ZERO}), ZERO)
        self.assertEqual(day_value(MON, {MON: HALF}), HALF)


class LocalDateTests(SimpleTestCase):
    """completed_at is stored UTC; lateness must use the Istanbul calendar date."""

    def test_late_evening_utc_is_next_day_in_istanbul(self):
        # 21:30 UTC = 00:30 Istanbul (UTC+3) the next day
        dt = datetime(2026, 7, 3, 21, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(local_date(dt), date(2026, 7, 4))

    def test_midday_utc_is_same_day(self):
        dt = datetime(2026, 7, 3, 12, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(local_date(dt), date(2026, 7, 3))

    def test_none_passthrough(self):
        self.assertIsNone(local_date(None))


class ClassificationTests(SimpleTestCase):
    """_classify(status, target_end, end_variance, overdue) precedence."""

    def test_cancelled_and_skipped_are_excluded(self):
        self.assertEqual(_classify('cancelled', FRI, None, None), 'excluded')
        self.assertEqual(_classify('skipped', None, None, None), 'excluded')

    def test_no_target_date_is_unplanned(self):
        self.assertEqual(_classify('pending', None, None, None), 'unplanned')
        self.assertEqual(_classify('completed', None, None, None), 'unplanned')

    def test_completed_late_vs_on_time(self):
        self.assertEqual(_classify('completed', FRI, Decimal('2'), None), 'completed_late')
        self.assertEqual(_classify('completed', FRI, Decimal('0'), None), 'completed_on_time')
        self.assertEqual(_classify('completed', FRI, Decimal('-1'), None), 'completed_on_time')
        self.assertEqual(_classify('completed', FRI, None, None), 'completed_on_time')

    def test_open_task_past_target_is_overdue(self):
        self.assertEqual(_classify('in_progress', FRI, None, Decimal('3')), 'overdue')
        self.assertEqual(_classify('pending', FRI, None, Decimal('0.5')), 'overdue')

    def test_open_task_states(self):
        self.assertEqual(_classify('in_progress', FRI, None, None), 'in_progress')
        self.assertEqual(_classify('on_hold', FRI, None, None), 'in_progress')
        self.assertEqual(_classify('pending', FRI, None, None), 'not_started')
        self.assertEqual(_classify('blocked', FRI, None, None), 'not_started')
