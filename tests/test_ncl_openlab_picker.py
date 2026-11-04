"""Offline validation for the Windows/macOS date + ordered two-slot picker."""
import ast
import sys
import unittest
from datetime import date
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from ncl_openlab_picker_model import (
    ROOM_CHOICES, available_slots, build_booking_args,
    console_python, release_datetime,
)


class PickerModelTests(unittest.TestCase):
    def test_room_lists_match_real_ncl_time_blocks(self):
        self.assertEqual(available_slots("music"),
                         ("09:00-12:00", "13:00-16:00", "17:00-20:00"))
        self.assertEqual(available_slots("p03")[0], "09:00-10:00")
        self.assertEqual(available_slots("p03")[-1], "19:00-20:00")
        self.assertEqual(len(ROOM_CHOICES), 14)
        self.assertEqual(available_slots("discussion"), ())
        self.assertEqual(available_slots("av_onsite"), ())

    def test_calendar_date_release_timezone(self):
        release = release_datetime(date(2026, 11, 12))
        self.assertEqual(release.isoformat(), "2026-11-05T00:00:00+08:00")

    def test_one_selected_slot_means_one_booking(self):
        argv = build_booking_args(
            day=date(2026, 11, 12), room="music",
            slots=["13:00-16:00"], auto_submit=True)
        self.assertEqual(argv[:6], [
            "--room", "music", "--date", "2026-11-12",
            "--slots", "13:00-16:00"])
        self.assertIn("--auto-submit", argv)
        self.assertNotIn("--reserve-two", argv)
        self.assertNotIn("--now", argv)

    def test_two_music_slots_means_exactly_two_bookings(self):
        argv = build_booking_args(
            day=date(2026, 11, 12), room="music",
            slots=["17:00-20:00", "13:00-16:00"],
            auto_submit=True, accept_terms=True)
        self.assertIn("--reserve-two", argv)
        self.assertIn("--accept-terms", argv)
        self.assertEqual(argv[argv.index("--slots")+1],
                         "17:00-20:00,13:00-16:00")

    def test_two_p03_slots_means_exactly_two_bookings(self):
        argv = build_booking_args(
            day=date(2026, 11, 12), room="p03",
            slots=["14:00-15:00", "13:00-14:00"],
            auto_submit=True, immediate=True)
        self.assertIn("--reserve-two", argv)
        self.assertIn("--now", argv)
        self.assertEqual(argv[argv.index("--slots")+1],
                         "14:00-15:00,13:00-14:00")

    def test_no_explicit_submit_consent_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "授權"):
            build_booking_args(day=date(2026, 11, 12), room="music",
                               slots=["13:00-16:00"], auto_submit=False)

    def test_rejects_zero_three_duplicates_and_wrong_room_slot(self):
        for room, slots in (
            ("music", []),
            ("music", ["09:00-12:00", "13:00-16:00", "17:00-20:00"]),
            ("music", ["09:00-12:00", "09:00-12:00"]),
            ("p03", ["09:00-12:00"]),
            ("unknown", ["13:00-16:00"]),
        ):
            with self.subTest(room=room, slots=slots):
                with self.assertRaises(ValueError):
                    build_booking_args(day=date(2026, 11, 12),
                                       room=room, slots=slots,
                                       auto_submit=True)

    def test_invalid_date_fails_closed(self):
        for invalid in ("2026-11-12", None):
            with self.assertRaises(ValueError):
                build_booking_args(day=invalid, room="music",
                                   slots=["13:00-16:00"], auto_submit=True)

    def test_gui_spawn_uses_console_python_not_pythonw(self):
        self.assertEqual(
            console_python(r"C:\Users\Frankie\ncl-openlab\.venv\Scripts\pythonw.exe"),
            r"C:\Users\Frankie\ncl-openlab\.venv\Scripts\python.exe",
        )
        self.assertEqual(
            console_python(r"C:\Python311\python.exe"),
            r"C:\Python311\python.exe",
        )

    def test_high_dpi_layout_has_fixed_action_footer_and_scrollable_config(self):
        source = (SRC / "ncl_openlab_picker.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertIsNotNone(tree)
        self.assertIn('footer.pack(side="bottom", fill="x")', source)
        self.assertIn('viewport.pack(side="top", fill="both", expand=True)', source)
        self.assertIn('scrollregion=self.content_canvas.bbox("all")', source)
        self.assertIn('self.content_canvas.create_window(', source)
        self.assertIn('self.content_canvas.bind_all("<MouseWheel>"', source)
        self.assertEqual(source.count("self.summary = tk.Label"), 1)
        self.assertEqual(source.count('text="確認設定並開啟預約瀏覽器"'), 1)
        self.assertLess(
            source.index('footer.pack(side="bottom", fill="x")'),
            source.index('viewport.pack(side="top", fill="both", expand=True)'),
        )

    def test_immediate_mode_is_explicitly_real_booking_not_a_mock(self):
        source = (SRC / "ncl_openlab_picker.py").read_text(encoding="utf-8")
        self.assertIn("立即正式預約（不等午夜；會真的送出；預設關閉）", source)
        self.assertIn("立即正式預約（真實送出；無午夜重試）", source)
        self.assertNotIn("立即測試（不等午夜", source)

    def test_release_script_cannot_launch_reservation(self):
        script = (SRC.parent / "verify_ncl_release.ps1").read_text(encoding="utf-8")
        self.assertIn("NCL_RELEASE_GATE_PASS", script)
        self.assertIn("py_compile", script)
        self.assertIn("unittest discover", script)
        self.assertIn("feat/ncl-openlab-booking", script)
        self.assertNotIn("Start-Process", script)
        self.assertNotIn("--auto-submit", script)

    def test_gui_source_parses_without_opening_window(self):
        source = (SRC / "ncl_openlab_picker.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        classes = [node.name for node in tree.body
                   if isinstance(node, ast.ClassDef)]
        self.assertIn("BookingPicker", classes)
        self.assertIn("messagebox.askyesno", source)
        self.assertIn("launch_booking_command(command, entry.parent.parent)", source)
        self.assertIn("from ncl_openlab_launcher import launch_booking_command", source)
        launch_source = (SRC / "ncl_openlab_launcher.py").read_text(encoding="utf-8")
        self.assertIn("subprocess.Popen", launch_source)
        self.assertIn("CREATE_NEW_CONSOLE", launch_source)
        self.assertIn("osascript", launch_source)
        self.assertIn("self.slots.append(value)", source)
        self.assertIn("self.slots.remove(value)", source)
        self.assertIn("len(self.slots) >= 2", source)
        self.assertIn("calendar.Calendar", source)


if __name__ == "__main__":
    unittest.main()
