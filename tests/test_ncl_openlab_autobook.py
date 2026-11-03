"""Offline safety checks for a single-shot, opt-in NCL reservation workflow."""
import asyncio
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ncl_openlab_autobook import (
    PHASES, action_script, release_time, seconds_until_release,
    attempt_stage
)


DAY = date(2026, 11, 12)
SLOT = "09:00-12:00"


class AutoBookTests(unittest.TestCase):
    def test_all_steps_include_real_ui_selection_and_submit(self):
        self.assertEqual(PHASES, ("date", "room", "slot", "next",
                                  "submit", "success"))

    def test_music_room_uses_true_timebox2(self):
        js = action_script("slot", DAY, SLOT)
        self.assertIn(".time-box2[data-param1]", js)
        self.assertIn('"09:00-12:00"', js)
        self.assertIn('"音樂創作室"', js)

    def test_explicit_book_ui_hint(self):
        js = action_script("slot", DAY, SLOT)
        self.assertIn('classList.contains("book")', js)
        self.assertIn('SLOT_NOT_BOOK_CLASS', js)

    def test_disabling_and_reserving_are_hard_blocks(self):
        js = action_script("slot", DAY, SLOT)
        self.assertIn('classList.contains("disabled")', js)
        self.assertIn('classList.contains("reserving")', js)
        self.assertIn('"SLOT_DISABLED"', js)

    def test_date_and_room_must_be_selected(self):
        js = action_script("slot", DAY, SLOT)
        self.assertIn(".date-box", js)
        self.assertIn(".space-box1", js)
        self.assertIn('classList.contains("selected")', js)
        self.assertIn('"CONTEXT_NOT_SELECTED"', js)

    def test_exact_final_summary_and_single_submission(self):
        js = action_script("submit", DAY, SLOT)
        self.assertIn('"2026/11/12"', js)
        self.assertIn('"音樂創作室"', js)
        self.assertIn('summary()', js)
        self.assertIn('window.__nclOneShotSubmit', js)
        self.assertIn('button#gobook.submit-circle-button', js)
        self.assertIn('button.getAttribute("data-param2") !== task.isoDate', js)
        self.assertIn('button.getAttribute("data-param5") !== task.slot', js)
        self.assertIn('READY_FOR_POINTER_CLICK', js)
        self.assertNotIn('button.click(); return result("CLICKED_ONCE")', js)

    def test_no_private_details_reported(self):
        js = action_script("success", DAY, SLOT)
        self.assertIn("SUCCESS_PAGE_MATCHED", js)
        self.assertIn("SUCCESS_NOT_VERIFIED", js)
        self.assertNotIn("document.cookie", js)
        self.assertNotIn("localStorage", js)
        self.assertNotIn("sessionStorage", js)
        self.assertNotIn("email", js.lower())

    def test_no_backend_api_or_captcha_bypass(self):
        js = action_script("submit", DAY, SLOT)
        for forbidden in ("fetch(", "XMLHttpRequest", "webdriver",
                          "captcha", "CAPTCHA", "turnstile", "axios",
                          "location.reload(", "setInterval("):
            self.assertNotIn(forbidden, js)

    def test_invalid_phase_rejected(self):
        with self.assertRaises(ValueError):
            action_script("checkout_anything", DAY, SLOT)

    def test_invalid_one_hour_slot_rejected(self):
        with self.assertRaises(ValueError):
            action_script("slot", DAY, "09:00-10:00")

    def test_invalid_datetime_target_rejected(self):
        with self.assertRaises(ValueError):
            action_script("date", datetime(2026, 11, 12), SLOT)

    def test_release_day_is_seven_days_before(self):
        self.assertEqual(release_time(DAY).isoformat(),
                         "2026-11-05T00:00:00+08:00")

    def test_release_difference_is_taipei_timezone(self):
        current = datetime(2026, 11, 4, 23, 58, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(seconds_until_release(DAY, current), 120.0)

    def test_local_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            seconds_until_release(DAY, datetime(2026, 11, 4, 23, 58))

    def test_unsupported_older_date_rejected(self):
        with self.assertRaises(ValueError):
            release_time(datetime(2026, 11, 12))

    def test_single_pointer_click_does_not_repeat_when_uncertain(self):
        import ncl_openlab_autobook as module

        class FakeTab:
            def __init__(self, failure=False):
                self.failure = failure
                self.events = []

            async def evaluate(self, code):
                self.events.append("evaluate")
                if code == "location.href":
                    return "https://spms.ncl.edu.tw/confirmation"
                return {"code": "READY_FOR_POINTER_CLICK", "x": 200.0, "y": 350.0}

            async def mouse_click(self, x, y):
                self.events.append(("mouse_click", x, y))
                if self.failure:
                    raise RuntimeError("unsure whether event arrived")

        async def one(tab):
            return await module.submit_once_with_pointer(
                tab, DAY, SLOT, mode="music", attempts=8)

        tab = FakeTab()
        self.assertEqual(asyncio.run(one(tab)), "CLICKED_ONCE")
        self.assertEqual([e for e in tab.events if isinstance(e, tuple)],
                         [("mouse_click", 200.0, 350.0)])
        bad = FakeTab(failure=True)
        self.assertEqual(asyncio.run(one(bad)),
                         "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY")
        self.assertEqual(len([e for e in bad.events if isinstance(e, tuple)]), 1)

    def test_bad_pointer_payload_fails_closed(self):
        import ncl_openlab_autobook as module
        class FakeTab:
            async def evaluate(self, code):
                if code == "location.href":
                    return "https://spms.ncl.edu.tw/"
                return {"code": "READY_FOR_POINTER_CLICK",
                        "x": "not a number", "y": 200}

            async def mouse_click(self, x, y):
                raise AssertionError("must not mouse click")
        self.assertEqual(
            asyncio.run(module.submit_once_with_pointer(
                FakeTab(), DAY, SLOT, attempts=1)),
            "INVALID_SUBMIT_COORDINATES")

    def test_dom_retry_stops_on_disabled(self):
        class Tab:
            def __init__(self):
                self.calls = 0

        async def fake_read(tab, phase, day, slot):
            tab.calls += 1
            return "SLOT_DISABLED"

        import ncl_openlab_autobook as module
        original = module.read_action
        module.read_action = fake_read
        try:
            tab = Tab()
            self.assertEqual(asyncio.run(attempt_stage(
                tab, "slot", DAY, SLOT, attempts=8)), "SLOT_DISABLED")
            self.assertEqual(tab.calls, 1)
        finally:
            module.read_action = original

    def test_submit_does_not_retry_after_click(self):
        class Tab:
            def __init__(self):
                self.calls = 0

        async def fake_read(tab, phase, day, slot):
            tab.calls += 1
            return "CLICKED_ONCE"

        import ncl_openlab_autobook as module
        original = module.read_action
        module.read_action = fake_read
        try:
            tab = Tab()
            self.assertEqual(asyncio.run(attempt_stage(
                tab, "submit", DAY, SLOT, attempts=8)), "CLICKED_ONCE")
            self.assertEqual(tab.calls, 1)
        finally:
            module.read_action = original


if __name__ == "__main__":
    unittest.main()
