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

    def test_room_prefix_exact_p03_not_neighbor_room(self):
        js = app.action_script("room", DAY, SLOT, "p03")
        self.assertIn(r"/^P03(?:\s|$)/", js)
        self.assertIn('from(".space-box1")', js)
        self.assertNotIn('querySelectorAll("*")', js)
        self.assertNotIn('task.roomId', js)

    def test_p03_uses_room_specific_final_confirmation(self):
        js = app.action_script("submit", DAY, SLOT, "p03")
        self.assertIn('"個人直播室"', js)
        self.assertIn(r"/\bP03\b/", js)
        self.assertIn('"2026/11/11"', js)
        self.assertIn('"13:00-14:00"', js)
        self.assertIn('if (!summary()) return result("SUMMARY_MISMATCH")', js)
        self.assertIn('button.click(); return result("CLICKED_ONCE")', js)

    def test_vertical_room_label_whitespace_is_normalized(self):
        js = app.action_script("submit", DAY, SLOT, "p03")
        self.assertIn('display.replace(/\\s+/g, "").includes("個人直播室")', js)
        self.assertIn(r"/\bP03\b/", js)

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
        self.assertIn('!chosen(slotTile())', js)
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
