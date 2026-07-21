from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from projects.serializers import (
    MEETING_TZ,
    _baseline_pct,
    _daily_series,
    _last_week_boundaries,
    _pct_at,
    _pct_before,
)


def _log(when, old_pct, new_pct):
    """Minimal stand-in for a JobOrderProgressLog row (these helpers are pure)."""
    return SimpleNamespace(
        logged_at=when.replace(tzinfo=MEETING_TZ) if when.tzinfo is None else when,
        old_pct=Decimal(str(old_pct)),
        new_pct=Decimal(str(new_pct)),
    )


class DailySeriesTests(SimpleTestCase):
    """
    Daily 20:00→20:00 progress buckets.

    Regression cover for job 009-37, whose first log landed at 07:44 — before the
    20:00 boundary of its own date. The series used to open at that date's 20:00,
    silently dropping the 0→15% earned that morning, so the deltas summed to 5.00
    while last_week_progress reported 20.00.
    """

    # Freeze "now" just after the 20 Jul 20:00 boundary closes.
    NOW = datetime(2026, 7, 21, 9, 26, tzinfo=MEETING_TZ)

    LOGS_009_37 = [
        _log(datetime(2026, 7, 14, 7, 44), 0.00, 10.00),
        _log(datetime(2026, 7, 14, 8, 30), 10.00, 15.00),
        _log(datetime(2026, 7, 17, 15, 24), 15.00, 20.00),
        _log(datetime(2026, 7, 17, 15, 47), 20.00, 17.38),
        _log(datetime(2026, 7, 17, 16, 17), 17.38, 16.81),
        _log(datetime(2026, 7, 20, 11, 39), 16.81, 18.01),
        _log(datetime(2026, 7, 20, 14, 33), 18.01, 20.00),
    ]

    def _series(self, logs):
        with patch('projects.serializers._meeting_now', return_value=self.NOW):
            return _daily_series(logs)

    def test_first_partial_day_is_not_dropped(self):
        series = self._series(self.LOGS_009_37)

        self.assertEqual(
            [(d['date'], d['delta']) for d in series],
            [
                ('2026-07-14', 15.00),  # the morning jump, previously lost
                ('2026-07-15', 0.00),
                ('2026-07-16', 0.00),
                ('2026-07-17', 1.81),
                ('2026-07-18', 0.00),
                ('2026-07-19', 0.00),
                ('2026-07-20', 3.19),
            ],
        )

    def test_deltas_sum_to_total_gain(self):
        """The invariant that keeps daily_avg and last_week_progress consistent."""
        series = self._series(self.LOGS_009_37)
        total = round(sum(d['delta'] for d in series), 2)
        baseline = _baseline_pct(self.LOGS_009_37)

        self.assertEqual(total, round(series[-1]['completion_pct'] - baseline, 2))
        self.assertEqual(total, 20.00)

    def test_last_week_matches_sum_of_deltas(self):
        with patch('projects.serializers._meeting_now', return_value=self.NOW):
            series = _daily_series(self.LOGS_009_37)
            window_start, window_end = _last_week_boundaries()
            baseline = _baseline_pct(self.LOGS_009_37)
            last_week = round(
                _pct_before(self.LOGS_009_37, window_end)
                - _pct_at(self.LOGS_009_37, window_start, baseline),
                2,
            )

        self.assertEqual(last_week, round(sum(d['delta'] for d in series), 2))

    def test_log_after_cutoff_opens_next_window(self):
        """A 21:00 log belongs to the window closing the *following* day."""
        logs = [
            _log(datetime(2026, 7, 14, 21, 0), 0.00, 5.00),
            _log(datetime(2026, 7, 15, 10, 0), 5.00, 8.00),
        ]
        series = self._series(logs)

        self.assertEqual(series[0]['date'], '2026-07-15')
        self.assertEqual(series[0]['delta'], 8.00)

    def test_baseline_uses_old_pct_not_zero(self):
        """
        Jobs whose logging began mid-flight must not be credited with the
        progress they had before the first log (e.g. 009-34 starts at 78.75%).
        """
        logs = [
            _log(datetime(2026, 7, 14, 9, 0), 78.75, 80.00),
            _log(datetime(2026, 7, 16, 9, 0), 80.00, 85.00),
        ]

        self.assertEqual(_baseline_pct(logs), 78.75)

        series = self._series(logs)
        self.assertEqual(series[0]['delta'], 1.25)
        self.assertEqual(round(sum(d['delta'] for d in series), 2), 6.25)

    def test_decreases_are_preserved(self):
        """Recomputes can lower a percentage; deltas go negative rather than clamp."""
        logs = [
            _log(datetime(2026, 7, 14, 9, 0), 40.00, 50.00),
            _log(datetime(2026, 7, 16, 9, 0), 50.00, 45.00),
        ]
        series = self._series(logs)

        self.assertEqual(series[0]['delta'], 10.00)
        self.assertEqual(series[2]['delta'], -5.00)

    def test_empty_logs(self):
        self.assertEqual(self._series([]), [])
        self.assertEqual(_baseline_pct([]), 0.0)

    def test_logs_entirely_within_open_window_yield_no_closed_days(self):
        """Logged today, before tonight's 20:00 — nothing has closed yet."""
        logs = [_log(datetime(2026, 7, 21, 8, 0), 0.00, 5.00)]

        self.assertEqual(self._series(logs), [])


class WindowBoundaryTests(SimpleTestCase):
    """The rolling 7-day window that backs "Son Hafta"."""

    def test_window_is_seven_days_ending_at_last_closed_cutoff(self):
        now = datetime(2026, 7, 21, 9, 26, tzinfo=MEETING_TZ)
        with patch('projects.serializers._meeting_now', return_value=now):
            start, end = _last_week_boundaries()

        self.assertEqual(end.date(), date(2026, 7, 20))
        self.assertEqual(end.hour, 20)
        self.assertEqual(end - start, timedelta(days=7))

    def test_window_rolls_forward_after_2000(self):
        before = datetime(2026, 7, 21, 19, 59, tzinfo=MEETING_TZ)
        after = datetime(2026, 7, 21, 20, 1, tzinfo=MEETING_TZ)

        with patch('projects.serializers._meeting_now', return_value=before):
            _, end_before = _last_week_boundaries()
        with patch('projects.serializers._meeting_now', return_value=after):
            _, end_after = _last_week_boundaries()

        self.assertEqual(end_before.date(), date(2026, 7, 20))
        self.assertEqual(end_after.date(), date(2026, 7, 21))
