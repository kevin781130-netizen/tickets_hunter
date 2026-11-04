"""Offline equivalence checks for the extracted cross-platform booking primitives."""
import asyncio
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reservation_common import (
    has_retry_budget, release_datetime, seconds_until,
)
from reservation_browser import wait_until_browser_manually_closed
import ncl_openlab_autobook as ncl
from ncl_openlab_picker_model import release_datetime as gui_release_datetime


class SharedCoreTests(unittest.TestCase):
    def test_ncl_and_gui_identical_release_midnight(self):
        d = date(2026, 11, 12)
        expected = "2026-11-05T00:00:00+08:00"
        self.assertEqual(ncl.release_time(d).isoformat(), expected)
        self.assertEqual(gui_release_datetime(d).isoformat(), expected)
        self.assertEqual(
            release_datetime(d, days_before=7,
                             tz=timezone(timedelta(hours=8))).isoformat(),
            expected)

    def test_reusable_different_release_horizon(self):
        d = date(2026, 11, 12)
        self.assertEqual(
            release_datetime(d, days_before=14, tz=timezone.utc).isoformat(),
            "2026-10-29T00:00:00+00:00")

    def test_rejects_invalid_target_dates(self):
        tz = timezone(timedelta(hours=8))
        for invalid in ("2026-11-12", None, datetime(2026, 11, 12)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    release_datetime(invalid, days_before=7, tz=tz)

    def test_rejects_invalid_release_horizons_and_timezone(self):
        day = date(2026, 11, 12)
        for bad in (-1, True, 7.1, "7"):
            with self.assertRaises(ValueError):
                release_datetime(day, days_before=bad, tz=timezone.utc)
        with self.assertRaises(ValueError):
            release_datetime(day, days_before=7, tz=None)

    def test_ncl_seconds_until_same_as_old_behavior(self):
        day = date(2026, 11, 12)
        now = datetime(2026, 11, 4, 23, 58,
                       tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(ncl.seconds_until_release(day, now), 120.0)
        self.assertEqual(seconds_until(ncl.release_time(day), now), 120.0)

    def test_cross_timezone_clock_conversion(self):
        day = date(2026, 11, 12)
        utc_now = datetime(2026, 11, 4, 15, 58, tzinfo=timezone.utc)
        self.assertEqual(ncl.seconds_until_release(day, utc_now), 120.0)

    def test_rejects_naive_now(self):
        with self.assertRaises(ValueError):
            seconds_until(ncl.release_time(date(2026, 11, 12)),
                          datetime(2026, 11, 4, 23, 58))

    def test_retry_budget_matches_old_boundary(self):
        self.assertTrue(has_retry_budget(now=95, deadline=100, interval=5))
        self.assertFalse(has_retry_budget(now=96, deadline=100, interval=5))
        self.assertFalse(has_retry_budget(now=100, deadline=100, interval=3))

    def test_ncl_uses_exact_same_browser_lifecycle_helper(self):
        self.assertIs(ncl.wait_until_browser_manually_closed,
                      wait_until_browser_manually_closed)

    def test_passive_browser_monitor_never_closes_chrome(self):
        polls = []

        class Page:
            type_ = "page"

        class Browser:
            stopped = False

            async def _get_targets(self):
                polls.append("check")
                return [Page()] if len(polls) < 3 else []

            async def stop(self):
                raise AssertionError("must never close the user's browser")

        async def fake_sleep(seconds):
            return None

        with patch("reservation_browser.asyncio.sleep", fake_sleep):
            asyncio.run(wait_until_browser_manually_closed(Browser()))
        self.assertEqual(len(polls), 5)

    def test_shared_modules_do_not_import_platforms_or_submit(self):
        root = Path(__file__).resolve().parents[1] / "src"
        for module in ("reservation_common.py", "reservation_browser.py"):
            text = (root / module).read_text(encoding="utf-8")
            self.assertNotIn("spms.ncl", text)
            self.assertNotIn("from platforms", text)
            self.assertNotIn("browser.stop()", text.replace("browser.stop() calls", ""))


if __name__ == "__main__":
    unittest.main()
