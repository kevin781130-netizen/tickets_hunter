"""P03 one-hour booking mode: explicit targeting, no cross-room submissions."""
import contextlib
from datetime import date
from io import StringIO
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ncl_openlab_autobook as app


DAY = date(2026, 11, 11)
SLOT = "13:00-14:00"


class P03ModeTests(unittest.TestCase):
    def test_p03_hourly_slot_allowlist(self):
        self.assertEqual(len(app.P03_SLOTS), 11)
        self.assertEqual(app.P03_SLOTS[0], "09:00-10:00")
        self.assertEqual(app.P03_SLOTS[-1], "19:00-20:00")
        self.assertIn(SLOT, app.P03_SLOTS)

    def test_p03_uses_only_hourly_time_box(self):
        js = app.action_script("slot", DAY, SLOT, "p03")
        self.assertIn('"mode": "p03"', js)
        self.assertIn('task.mode === "p03"', js)
        self.assertIn('".time-box[data-param1]" : ".time-box2[data-param1]"', js)
        self.assertIn('"13:00-14:00"', js)

    def test_p03_room_uses_actual_exact_child_data_attributes(self):
        """Live 11/04 markup: #boxspace2.space-box1.selected > span.space-num2."""
        js = app.action_script("room", DAY, SLOT, "p03")
        self.assertIn('from(".space-box1")', js)
        self.assertIn('span.space-num2[data-en="P03"][data-zh="P03"]', js)
        self.assertIn('cleanText(label) === "P03"', js)
        self.assertIn("const p03Label = (el) => exactOne(", js)
        self.assertIn('const roomTile = () => exactOne(', js)
        self.assertIn('task.mode === "p03"', js)
        # Other room tiles, parent text, and arbitrary page text cannot match.
        self.assertNotIn(r'/^P03(?:\s|$)/', js)
        self.assertNotIn('".space-box1, .space-box2, .space-box3"', js)
        self.assertNotIn('querySelectorAll("*")', js)
        self.assertNotIn('task.roomId', js)

    def test_p03_already_selected_room_does_not_click_again(self):
        js = app.action_script("room", DAY, SLOT, "p03")
        self.assertIn('if (chosen(tile)) return result("ALREADY_SELECTED")', js)
        self.assertIn('if (!chosen(dateTile())) return result("DATE_NOT_SELECTED")', js)
        self.assertIn('if (!tile) return result("ROOM_NOT_UNIQUE")', js)

    def test_p03_uses_room_specific_final_confirmation(self):
        js = app.action_script("submit", DAY, SLOT, "p03")
        self.assertIn('"個人直播室"', js)
        self.assertIn(r"/\bP03\b/", js)
        self.assertIn('"2026/11/11"', js)
        self.assertIn('"13:00-14:00"', js)
        self.assertIn('if (!summary()) return result("SUMMARY_MISMATCH")', js)
        self.assertIn('button#gobook.submit-circle-button', js)
        self.assertIn('READY_FOR_POINTER_CLICK', js)
        self.assertNotIn('button.click(); return result("CLICKED_ONCE")', js)

    def test_vertical_room_label_whitespace_is_normalized(self):
        js = app.action_script("submit", DAY, SLOT, "p03")
        self.assertIn('display.replace(/\\s+/g, "").includes("個人直播室")', js)
        self.assertIn(r"/\bP03\b/", js)

    def test_spaced_booking_button_label_is_normalized(self):
        """Live #gobook shows '預 約'; final CTA compares its exact normalized label."""
        js = app.action_script("submit", DAY, SLOT, "p03")
        self.assertIn('from("button#gobook.submit-circle-button")', js)
        self.assertIn(r'cleanText(button).replace(/\s+/g, "") !== "預約"', js)
        self.assertIn('const button = exactOne(buttons)', js)
        self.assertIn('if (!summary()) return result("SUMMARY_MISMATCH")', js)
        self.assertIn('return {code: "READY_FOR_POINTER_CLICK", x, y}', js)

    def test_spaced_label_preserves_single_submit_guard(self):
        js = app.action_script("submit", DAY, SLOT, "p03")
        self.assertIn('window.__nclOneShotSubmit === true', js)
        self.assertIn('window.__nclOneShotSubmit = true', js)
        self.assertIn('button#gobook.submit-circle-button', js)
        self.assertIn('READY_FOR_POINTER_CLICK', js)
        self.assertNotIn('button.click(); return result("CLICKED_ONCE")', js)
        self.assertNotIn('location.reload(', js)

    def test_live_gobook_target_matches_exact_date_and_one_hour_slot(self):
        js = app.action_script("submit", DAY, SLOT, "p03")
        self.assertIn('"isoDate": "2026-11-11"', js)
        self.assertIn('button.getAttribute("data-param2") !== task.isoDate', js)
        self.assertIn('button.getAttribute("data-param5") !== task.slot', js)
        self.assertIn('SUBMIT_TARGET_MISMATCH', js)
        self.assertIn('document.elementFromPoint(x, y)', js)
        self.assertIn('window.__nclOneShotSubmit = true', js)
        self.assertNotIn('data-param3', js)

    def test_p03_success_must_match_date_room_and_slot(self):
        js = app.action_script("success", DAY, SLOT, "p03")
        self.assertIn('matchingRoomSummary(display)', js)
        self.assertIn('display.includes(task.fullDate)', js)
        self.assertIn('display.includes(task.slot)', js)
        self.assertIn('display.includes("預約成功")', js)

    def test_p03_normal_time_box_can_be_clicked_before_book_class(self):
        js = app.action_script("slot", DAY, SLOT, "p03")
        # Previously P03 stopped at SLOT_NOT_BOOK_CLASS before clicking.
        self.assertIn('task.mode !== "p03" && !tile.classList.contains("book")', js)
        self.assertIn('if (chosen(tile, "slot")) return result("ALREADY_SELECTED")', js)
        self.assertIn('tile.click(); return result("CLICKED")', js)

    def test_p03_book_is_selected_state_for_next_step(self):
        js = app.action_script("next", DAY, SLOT, "p03")
        self.assertIn('kind === "slot" && el.classList.contains("book")', js)
        self.assertIn('!chosen(slotTile(), "slot")', js)
        self.assertIn('button.click(); return result("CLICKED")', js)

    def test_music_still_requires_book_class_for_slot(self):
        js = app.action_script("slot", DAY, "13:00-16:00", "music")
        self.assertIn('task.mode !== "p03" && !tile.classList.contains("book")', js)
        self.assertIn('SLOT_NOT_BOOK_CLASS', js)

    def test_p03_disabled_never_allowed(self):
        js = app.action_script("slot", DAY, SLOT, "p03")
        self.assertIn('if (disabled(tile)) return result("SLOT_DISABLED")', js)
        self.assertIn('classList.contains("reserving")', js)
        self.assertIn('!tile.classList.contains("book")', js)

    def test_fails_closed_when_room_not_selected(self):
        js = app.action_script("next", DAY, SLOT, "p03")
        self.assertIn('!chosen(dateTile()) || !chosen(roomTile())', js)
        self.assertIn('!chosen(slotTile(), "slot")', js)
        self.assertIn('TARGET_NOT_SELECTED', js)

    def test_p03_refuses_music_room_three_hour_slot(self):
        with self.assertRaises(ValueError):
            app.action_script("slot", DAY, "13:00-16:00", "p03")

    def test_music_mode_remains_separate(self):
        js = app.action_script("slot", DAY, "13:00-16:00")
        self.assertIn('"mode": "music"', js)
        self.assertIn('"音樂創作室"', js)
        with self.assertRaises(ValueError):
            app.action_script("slot", DAY, SLOT, "music")

    def test_unknown_room_mode_rejected(self):
        with self.assertRaises(ValueError):
            app.action_script("slot", DAY, SLOT, "p02")

    def test_no_api_replay_or_captcha_handling(self):
        js = app.action_script("submit", DAY, SLOT, "p03")
        for forbidden in ("fetch(", "XMLHttpRequest", "solveCaptcha",
                          "document.cookie", "localStorage", "setInterval("):
            self.assertNotIn(forbidden, js)

    def test_main_requires_explicit_p03_slot(self):
        args = ["app", "--date", "2026-11-11", "--room", "p03", "--now",
                "--auto-submit"]
        with patch.object(sys, "argv", args), contextlib.redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                app.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_main_passes_explicit_room_date_slot_and_consent(self):
        args = ["app", "--date", "2026-11-11", "--room", "p03",
                "--slot", SLOT, "--now", "--auto-submit"]
        with (patch.object(sys, "argv", args),
              patch.object(app.asyncio, "run", return_value="FAKE_BOOKING") as runner,
              contextlib.redirect_stdout(StringIO())):
            app.main()
        coro = runner.call_args.args[0]
        try:
            self.assertEqual(coro.cr_frame.f_locals["day"], DAY)
            self.assertEqual(coro.cr_frame.f_locals["priorities"], (SLOT,))
            self.assertTrue(coro.cr_frame.f_locals["auto_submit"])
            self.assertTrue(coro.cr_frame.f_locals["now_mode"])
            self.assertEqual(coro.cr_frame.f_locals["mode"], "p03")
        finally:
            coro.close()

    def test_p03_can_choose_one_hour_fallback_priority(self):
        args = ["app", "--date", "2026-11-11", "--room", "p03",
                "--slots", "13:00-14:00,14:00-15:00",
                "--now", "--auto-submit"]
        with (patch.object(sys, "argv", args),
              patch.object(app.asyncio, "run", return_value="MOCK") as runner,
              contextlib.redirect_stdout(StringIO())):
            app.main()
        coro = runner.call_args.args[0]
        try:
            self.assertEqual(coro.cr_frame.f_locals["priorities"],
                             ("13:00-14:00", "14:00-15:00"))
            self.assertEqual(coro.cr_frame.f_locals["mode"], "p03")
        finally:
            coro.close()

    def test_p03_fallback_rejects_duplicate_or_three_hour_slots(self):
        for raw in ("13:00-14:00,13:00-14:00",
                    "13:00-16:00,14:00-15:00",
                    "13:30-14:30", ""):
            with self.assertRaises(ValueError):
                app.parse_p03_priorities(raw)

    def test_p03_two_explicit_slots_are_accepted(self):
        args = ["app", "--date", "2026-11-12", "--room", "p03",
                "--slots", "13:00-14:00,14:00-15:00",
                "--reserve-two", "--now", "--auto-submit"]
        with (patch.object(sys, "argv", args),
              patch.object(app.asyncio, "run", return_value="MOCK") as runner,
              contextlib.redirect_stdout(StringIO())):
            app.main()
        coro = runner.call_args.args[0]
        try:
            params = coro.cr_frame.f_locals
            self.assertEqual(params["priorities"], ("13:00-14:00", "14:00-15:00"))
            self.assertEqual(params["mode"], "p03")
            self.assertTrue(params["reserve_two"])
        finally:
            coro.close()

    def test_two_p03_bookings_never_run_second_after_uncertain_first(self):
        import asyncio
        import types

        class FakeTab:
            def __init__(self):
                self.navigations = 0

            async def get(self, url):
                self.navigations += 1
                return self

        class FakeBrowser:
            stopped = True

            def __init__(self):
                self.tab = FakeTab()

            async def get(self, url):
                return self.tab

            async def stop(self):
                return None

        browser = FakeBrowser()

        async def start(**kwargs):
            return browser

        async def ready(*args, **kwargs):
            return "GRID_READY"

        async def prompt(*args, **kwargs):
            return ""

        calls = []

        async def reserve(tab, day, priorities, **kwargs):
            calls.append((priorities, kwargs["mode"]))
            return "SUBMITTED_SUCCESS_UNVERIFIED"

        with (patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(start=start)}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", prompt),
              patch.object(app, "book_one_target", reserve)):
            outcome = asyncio.run(app.autobook(
                DAY, ("13:00-14:00", "14:00-15:00"),
                auto_submit=True, now_mode=True, mode="p03",
                reserve_two=True))

        self.assertIn("FIRST_UNVERIFIED_SECOND_NOT_ATTEMPTED", outcome)
        self.assertEqual(calls, [(("13:00-14:00",), "p03")])
        self.assertEqual(browser.tab.navigations, 0)

    def test_main_defaults_to_no_final_submit(self):
        args = ["app", "--date", "2026-11-11", "--room", "p03",
                "--slot", SLOT, "--now"]
        with (patch.object(sys, "argv", args),
              patch.object(app.asyncio, "run", return_value="PREVIEW") as runner,
              contextlib.redirect_stdout(StringIO())):
            app.main()
        coro = runner.call_args.args[0]
        try:
            self.assertFalse(coro.cr_frame.f_locals["auto_submit"])
            self.assertEqual(coro.cr_frame.f_locals["mode"], "p03")
        finally:
            coro.close()


if __name__ == "__main__":
    unittest.main()
