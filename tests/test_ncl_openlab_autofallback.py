"""Offline regression for optional real-booking fallback. Never open Chrome."""
import asyncio
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import ncl_openlab_autobook as app
from ncl_openlab_picker_model import build_booking_args
from ncl_openlab_slots import ordered_slot_fallback

DAY = date(2026, 11, 11)


class FallbackPriorityTests(unittest.TestCase):
    def test_p03_pref_first_then_all_other_10_slots(self):
        selected = ("13:00-14:00",)
        order = ordered_slot_fallback(selected, app.P03_SLOTS)
        self.assertEqual(order[0], selected[0])
        self.assertEqual(len(order), 11)
        self.assertEqual(set(order), set(app.P03_SLOTS))
        self.assertEqual(order[1], "09:00-10:00")

    def test_first_booking_preserves_second_selected_slot(self):
        pref = ("13:00-16:00", "17:00-20:00")
        first = ordered_slot_fallback(pref, app.VALID_SLOTS, target_index=0)
        second = ordered_slot_fallback(
            pref, app.VALID_SLOTS, target_index=1, confirmed=("09:00-12:00",))
        self.assertEqual(first, ("13:00-16:00", "09:00-12:00", "17:00-20:00"))
        self.assertEqual(second, ("17:00-20:00", "13:00-16:00"))
        self.assertNotIn("09:00-12:00", second)

    def test_fallback_fails_closed_on_unknown_slot(self):
        for pref in ((), ("14:30-15:30",), ("13:00-14:00", "13:00-14:00")):
            with self.subTest(pref=pref), self.assertRaises(ValueError):
                ordered_slot_fallback(pref, app.P03_SLOTS)

    def test_gui_command_forwards_opt_in_and_must_authorize_submission(self):
        args = build_booking_args(
            day=DAY, room="p03", slots=["13:00-14:00"],
            immediate=True, auto_submit=True, fallback_any_slot=True)
        self.assertIn("--fallback-any-slot", args)
        self.assertIn("--auto-submit", args)
        self.assertIn("--now", args)
        with self.assertRaises(ValueError):
            build_booking_args(
                day=DAY, room="p03", slots=["13:00-14:00"],
                auto_submit=False, fallback_any_slot=True)

    def test_gui_displays_explicit_fallback_setting(self):
        src = (SRC / "ncl_openlab_picker.py").read_text(encoding="utf-8")
        self.assertIn("self.fallback_any_slot = tk.BooleanVar(value=True)", src)
        self.assertIn("fallback_any_slot=self.fallback_any_slot.get()", src)
        self.assertIn("偏好時段已滿時", src)


class RealBackendRoutingTests(unittest.TestCase):
    @staticmethod
    def fake_browser_module():
        class Tab:
            async def get(self, _url):
                return self
        class Browser:
            stopped = True
            async def get(self, _url):
                return Tab()
            async def stop(self):
                raise AssertionError("Never auto-close user's Chrome")
        return types.SimpleNamespace(start=AsyncMock(return_value=Browser()))

    def test_confirmed_two_booking_uses_different_slots_and_real_cli_order(self):
        calls = []
        async def ready(*args, **kwargs):
            return "GRID_READY"
        async def enter(*args, **kwargs):
            return ""
        async def reserve(tab, day, candidates, *, auto_submit, mode,
                          selected_log=None, **kwargs):
            calls.append((tuple(candidates), auto_submit, mode))
            actual = "12:00-13:00" if len(calls) == 1 else "13:00-14:00"
            self.assertIn(actual, candidates)
            selected_log.append(actual)
            return "SUCCESS_PAGE_MATCHED"

        with (patch.dict(sys.modules, {"zendriver": self.fake_browser_module()}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", enter),
              patch.object(app, "book_one_target", reserve)):
            result = asyncio.run(app.autobook(
                DAY, ("10:00-11:00", "13:00-14:00"),
                auto_submit=True, now_mode=True, mode="p03",
                reserve_two=True, fallback_any_slot=True))
        self.assertEqual(result, "TWO_BOOKINGS_CONFIRMED")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][0], "10:00-11:00")
        self.assertEqual(calls[1][0][0], "13:00-14:00")
        self.assertNotIn("12:00-13:00", calls[1][0])
        self.assertTrue(all(auth and room == "p03" for _,auth,room in calls))

    def test_uncertain_first_booking_stops_second(self):
        calls = []
        async def ready(*args, **kwargs):
            return "GRID_READY"
        async def enter(*args, **kwargs):
            return ""
        async def reserve(tab, day, candidates, **kwargs):
            calls.append(candidates)
            return "SUBMITTED_SUCCESS_UNVERIFIED"
        with (patch.dict(sys.modules, {"zendriver": self.fake_browser_module()}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", enter),
              patch.object(app, "book_one_target", reserve)):
            result = asyncio.run(app.autobook(
                DAY, ("10:00-11:00", "13:00-14:00"),
                auto_submit=True, now_mode=True, mode="p03",
                reserve_two=True, fallback_any_slot=True))
        self.assertTrue(result.startswith("FIRST_UNVERIFIED_SECOND_NOT_ATTEMPTED_"))
        self.assertEqual(len(calls), 1)

    def test_first_success_without_known_slot_stops_second(self):
        calls = []
        async def ready(*args, **kwargs):
            return "GRID_READY"
        async def enter(*args, **kwargs):
            return ""
        async def reserve(tab, day, candidates, **kwargs):
            calls.append(candidates)
            return "SUCCESS_PAGE_MATCHED"
        with (patch.dict(sys.modules, {"zendriver": self.fake_browser_module()}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", enter),
              patch.object(app, "book_one_target", reserve)):
            result = asyncio.run(app.autobook(
                DAY, ("10:00-11:00", "13:00-14:00"),
                auto_submit=True, now_mode=True, mode="p03",
                reserve_two=True, fallback_any_slot=True))
        self.assertEqual(result, "CONFIRMED_SLOT_ID_UNKNOWN_STOP")
        self.assertEqual(len(calls), 1)

    def test_second_booking_reenters_via_official_overview_not_login_root(self):
        urls, tabs_seen, selections = [], [], []
        class Tab:
            async def get(self, url):
                urls.append(url)
                return self
        tab = Tab()
        class Browser:
            stopped = True
            async def get(self, url):
                urls.append(url)
                return tab
        async def ready(*args, **kwargs):
            return "GRID_READY"
        async def enter(*args, **kwargs):
            return ""
        async def book(current_tab, day, candidates, *, selected_log=None,
                       **kwargs):
            tabs_seen.append(current_tab)
            chosen = "12:00-13:00" if len(tabs_seen) == 1 else "17:00-18:00"
            selections.append(chosen)
            self.assertIn(chosen, candidates)
            selected_log.append(chosen)
            return "SUCCESS_PAGE_MATCHED"
        with (patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(
                start=AsyncMock(return_value=Browser()))}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", enter),
              patch.object(app, "book_one_target", book)):
            status = asyncio.run(app.autobook(
                DAY, ("16:00-17:00", "17:00-18:00"),
                auto_submit=True, now_mode=True, mode="p03",
                reserve_two=True, fallback_any_slot=True))
        self.assertEqual(status, "TWO_BOOKINGS_CONFIRMED")
        self.assertEqual(urls, [app.NCL_URL, app.NCL_MULTIMEDIA_OVERVIEW_URL])
        self.assertIs(tabs_seen[0], tabs_seen[1])
        self.assertNotIn("12:00-13:00", selections[1:])

    def test_second_entry_login_redirect_stops_without_second_submit(self):
        urls, attempts, ready_calls = [], [], []
        class Tab:
            async def get(self, url):
                urls.append(url)
                return self
        class Browser:
            stopped = True
            async def get(self, url):
                urls.append(url)
                return Tab()
        async def ready(*args, **kwargs):
            ready_calls.append(1)
            return ("GRID_READY" if len(ready_calls) == 1
                    else "ENTRY_NOT_FOUND_OR_AMBIGUOUS")
        async def enter(*args, **kwargs):
            return ""
        async def book(tab, day, candidates, *, selected_log=None, **kwargs):
            attempts.append(1)
            selected_log.append("12:00-13:00")
            return "SUCCESS_PAGE_MATCHED"
        with (patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(
                start=AsyncMock(return_value=Browser()))}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", enter),
              patch.object(app, "book_one_target", book)):
            status = asyncio.run(app.autobook(
                DAY, ("16:00-17:00", "17:00-18:00"),
                auto_submit=True, now_mode=True, mode="p03",
                reserve_two=True, fallback_any_slot=True))
        self.assertEqual(
            status,
            "FIRST_CONFIRMED_SECOND_NOT_ATTEMPTED_"
            "GRID_NOT_READY_ENTRY_NOT_FOUND_OR_AMBIGUOUS")
        self.assertEqual(attempts, [1])
        self.assertEqual(urls, [app.NCL_URL, app.NCL_MULTIMEDIA_OVERVIEW_URL])

    def test_second_entry_navigation_error_stops_with_first_confirmed(self):
        attempts = []
        class Tab:
            async def get(self, url):
                raise RuntimeError("site unavailable or requires login")
        class Browser:
            stopped = True
            async def get(self, _url):
                return Tab()
        async def ready(*args, **kwargs):
            return "GRID_READY"
        async def enter(*args, **kwargs):
            return ""
        async def book(tab, day, candidates, *, selected_log=None, **kwargs):
            attempts.append(1)
            selected_log.append("12:00-13:00")
            return "SUCCESS_PAGE_MATCHED"
        with (patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(
                start=AsyncMock(return_value=Browser()))}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", enter),
              patch.object(app, "book_one_target", book)):
            status = asyncio.run(app.autobook(
                DAY, ("16:00-17:00", "17:00-18:00"),
                auto_submit=True, now_mode=True, mode="p03",
                reserve_two=True, fallback_any_slot=True))
        self.assertEqual(
            status, "FIRST_CONFIRMED_SECOND_NOT_ATTEMPTED_NAVIGATION_FAILED")
        self.assertEqual(attempts, [1])

    def test_single_booking_prefers_selected_before_other_options(self):
        seen = []
        async def ready(*args, **kwargs):
            return "GRID_READY"
        async def enter(*args, **kwargs):
            return ""
        async def reserve(tab, day, candidates, **kwargs):
            seen.append(candidates)
            return "NO_BOOKABLE_UI_SLOT"
        with (patch.dict(sys.modules, {"zendriver": self.fake_browser_module()}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", enter),
              patch.object(app, "book_one_target", reserve)):
            result = asyncio.run(app.autobook(
                DAY, ("13:00-14:00",), auto_submit=True,
                now_mode=True, mode="p03", fallback_any_slot=True))
        self.assertEqual(result, "NO_BOOKABLE_UI_SLOT")
        self.assertEqual(seen[0][0], "13:00-14:00")
        self.assertEqual(len(seen[0]), 11)

    def test_p03_unselected_tile_skips_to_real_selected_fallback(self):
        calls = []
        class Tab:
            async def evaluate(self, _code):
                return True
        async def stage(tab, phase, day, slot, attempts=6, mode="music"):
            calls.append((phase, slot))
            if phase in ("date", "room", "slot", "next"):
                return "CLICKED"
            raise AssertionError(phase)
        async def verify(tab, phase, day, slot, mode="music"):
            if phase == "verify-slot":
                return ("SLOT_NOT_SELECTED" if slot == "13:00-14:00"
                        else "ALREADY_SELECTED")
            if phase == "success":
                return "SUCCESS_PAGE_MATCHED"
            raise AssertionError(phase)
        async def submit(*args, **kwargs):
            return "CLICKED_ONCE"
        async def nap(_duration):
            return None
        chosen = []
        with (patch.object(app, "attempt_stage", stage),
              patch.object(app, "read_action", verify),
              patch.object(app, "submit_once_with_pointer", submit),
              patch.object(app.asyncio, "sleep", nap)):
            status = asyncio.run(app.book_one_target(
                Tab(), DAY, ("13:00-14:00", "12:00-13:00"),
                auto_submit=True, mode="p03", selected_log=chosen))
        self.assertEqual(status, "SUCCESS_PAGE_MATCHED")
        self.assertEqual(chosen, ["12:00-13:00"])
        self.assertIn(("slot", "13:00-14:00"), calls)
        self.assertIn(("slot", "12:00-13:00"), calls)
        self.assertIn(("next", "12:00-13:00"), calls)
        self.assertNotIn(("next", "13:00-14:00"), calls)

    def test_p03_delayed_book_class_is_accepted_after_six_readonly_checks(self):
        stages, verification = [], []
        async def stage(tab, phase, day, slot, attempts=6, mode="music"):
            stages.append((phase, slot))
            return "CLICKED"
        async def verify(tab, phase, day, slot, mode="music"):
            self.assertEqual(phase, "verify-slot")
            verification.append(slot)
            return ("SLOT_NOT_SELECTED" if len(verification) <= 5
                    else "ALREADY_SELECTED")
        async def nap(_duration):
            return None
        chosen = []
        with (patch.object(app, "attempt_stage", stage),
              patch.object(app, "read_action", verify),
              patch.object(app.asyncio, "sleep", nap)):
            result = asyncio.run(app.book_one_target(
                object(), DAY, ("17:00-18:00",),
                auto_submit=False, mode="p03", selected_log=chosen))
        self.assertEqual(result, "PREVIEW_STOPPED_BEFORE_SUBMIT")
        self.assertEqual(len(verification), 6)
        self.assertEqual(chosen, ["17:00-18:00"])
        self.assertIn(("next", "17:00-18:00"), stages)
        self.assertEqual([p for p, _ in stages].count("slot"), 1)

    def test_p03_never_advances_when_twelve_readonly_checks_fail(self):
        stages, verification = [], []
        async def stage(tab, phase, day, slot, attempts=6, mode="music"):
            stages.append((phase, slot))
            return "CLICKED"
        async def verify(tab, phase, day, slot, mode="music"):
            verification.append(slot)
            return "SLOT_NOT_SELECTED"
        async def nap(_duration):
            return None
        chosen = []
        with (patch.object(app, "attempt_stage", stage),
              patch.object(app, "read_action", verify),
              patch.object(app.asyncio, "sleep", nap)):
            result = asyncio.run(app.book_one_target(
                object(), DAY, ("17:00-18:00",),
                auto_submit=False, mode="p03", selected_log=chosen))
        self.assertEqual(result, "NO_BOOKABLE_UI_SLOT")
        self.assertEqual(len(verification), 12)
        self.assertEqual(chosen, [])
        self.assertNotIn("next", [phase for phase, _ in stages])

    def test_p03_context_lost_blocks_before_next(self):
        stages = []
        async def stage(tab, phase, day, slot, attempts=6, mode="music"):
            stages.append((phase, slot))
            return "CLICKED"
        async def verify(tab, phase, day, slot, mode="music"):
            return "CONTEXT_NOT_SELECTED"
        async def nap(_duration):
            return None
        with (patch.object(app, "attempt_stage", stage),
              patch.object(app, "read_action", verify),
              patch.object(app.asyncio, "sleep", nap)):
            result = asyncio.run(app.book_one_target(
                object(), DAY, ("17:00-18:00",),
                auto_submit=False, mode="p03"))
        self.assertEqual(result, "BLOCKED_CONTEXT_NOT_SELECTED")
        self.assertNotIn("next", [phase for phase, _ in stages])

    def test_slot_verification_is_read_only(self):
        script = app.action_script("verify-slot", DAY, "13:00-14:00", "p03")
        self.assertIn('task.phase === "verify-slot"', script)
        self.assertIn('return result(chosen(tile, "slot")', script)


if __name__ == "__main__":
    unittest.main()
