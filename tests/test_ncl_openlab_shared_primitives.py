"""Cross-platform offline contract tests for the independent shared primitives.

This deliberately does not modify or invoke the existing NCL booking engine.
"""
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reservation_common import has_retry_budget, release_datetime, seconds_until


class SharedPrimitivesContractTests(unittest.TestCase):
    def setUp(self):
        self.taipei = timezone(timedelta(hours=8))

    def test_seven_day_release_midnight_taipei(self):
        actual = release_datetime(date(2026, 11, 12), days_before=7, tz=self.taipei)
        self.assertEqual(actual.isoformat(), "2026-11-05T00:00:00+08:00")

    def test_other_horizon_remains_adapter_configurable(self):
        actual = release_datetime(date(2026, 11, 12), days_before=14, tz=timezone.utc)
        self.assertEqual(actual.isoformat(), "2026-10-29T00:00:00+00:00")

    def test_rejects_wrong_day_types(self):
        for value in (None, "2026-11-12", datetime(2026, 11, 12)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release_datetime(value, days_before=7, tz=self.taipei)

    def test_rejects_bad_horizons_and_timezone(self):
        for value in (-1, True, 7.5, "7"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release_datetime(date(2026, 11, 12), days_before=value, tz=self.taipei)
        with self.assertRaises(ValueError):
            release_datetime(date(2026, 11, 12), days_before=7, tz=None)

    def test_utc_clock_and_taipei_clock_are_equivalent(self):
        target = release_datetime(date(2026, 11, 12), days_before=7, tz=self.taipei)
        local = datetime(2026, 11, 4, 23, 58, tzinfo=self.taipei)
        utc = datetime(2026, 11, 4, 15, 58, tzinfo=timezone.utc)
        self.assertEqual(seconds_until(target, local), 120.0)
        self.assertEqual(seconds_until(target, utc), 120.0)

    def test_rejects_naive_datetime(self):
        target = release_datetime(date(2026, 11, 12), days_before=7, tz=self.taipei)
        with self.assertRaises(ValueError):
            seconds_until(target, datetime(2026, 11, 4, 23, 58))
        with self.assertRaises(ValueError):
            seconds_until(datetime(2026, 11, 5, 0), datetime.now(self.taipei))

    def test_retry_deadline_boundary(self):
        self.assertTrue(has_retry_budget(now=95, deadline=100, interval=5))
        self.assertFalse(has_retry_budget(now=96, deadline=100, interval=5))
        self.assertFalse(has_retry_budget(now=100, deadline=100, interval=3))

    def test_pure_module_never_imports_browser_or_booking_site(self):
        data = (Path(__file__).resolve().parents[1] / "src" / "reservation_common.py").read_text(encoding="utf-8")
        self.assertNotIn("spms.ncl", data)
        self.assertNotIn("from platforms", data)
        self.assertNotIn("webdriver", data)
        self.assertNotIn("zendriver", data)


if __name__ == "__main__":
    unittest.main()
