"""Offline validation for the Windows date + ordered two-slot picker."""
import ast
import sys
import unittest
from datetime import date, datetime, timedelta
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
        self.assertEqual(len(ROOM_CHOICES), 29)  # 11 engine rooms + 18 catalog-only units

    def test_calendar_date_release_timezone(self):
        release = release_datetime(date(2026, 11, 12))
        self.assertEqual(release.isoformat(), "2026-11-05T00:00:00+08:00")

    def test_one_selected_slot_means_one_booking(self):
        argv = build_booking_args(
            day=date(2026, 11, 12), room="p03",
            slots=["13:00-14:00"], auto_submit=True)
        self.assertEqual(argv[:6], [
            "--room", "p03", "--date", "2026-11-12",
            "--slots", "13:00-14:00"])
        self.assertIn("--auto-submit", argv)
        self.assertNotIn("--reserve-two", argv)
        self.assertNotIn("--now", argv)

    def test_two_verified_room_slots_means_exactly_two_bookings(self):
        argv = build_booking_args(
            day=date(2026, 11, 12), room="p03",
            slots=["17:00-18:00", "13:00-14:00"],
            auto_submit=True, accept_terms=True)
        self.assertIn("--reserve-two", argv)
        self.assertIn("--accept-terms", argv)
        self.assertEqual(argv[argv.index("--slots")+1],
                         "17:00-18:00,13:00-14:00")

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
        self.assertEqual(source.count('"啟動排程", self._start'), 1)
        self.assertLess(
            source.index('footer.pack(side="bottom", fill="x")'),
            source.index('viewport.pack(side="top", fill="both", expand=True)'),
        )

    def test_immediate_mode_is_explicitly_real_booking_not_a_mock(self):
        source = (SRC / "ncl_openlab_picker.py").read_text(encoding="utf-8")
        self.assertIn("立即執行（登入後馬上開始，會真的送出）", source)
        self.assertIn("將正式預約，並會真的送出", source)
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
        self.assertIn("RunSupervisor", source)
        self.assertNotIn("僅支援 Windows", source)
        self.assertNotIn('os.name == "nt"', source)
        self.assertIn("self.slots.append(value)", source)
        self.assertIn("self.slots.remove(value)", source)
        self.assertIn("len(self.slots) >= 2", source)
        self.assertIn("calendar.Calendar", source)


class ScheduleArgumentTests(unittest.TestCase):
    """GUI settings -> engine argv (the real parser accepts exactly this)."""

    def build(self, **kw):
        base = dict(day=date(2026, 11, 12), room="p03", slots=["13:00-14:00"], auto_submit=True)
        base.update(kw)
        return build_booking_args(**base)

    def test_custom_start_time_is_passed_with_its_timezone(self):
        from ncl_openlab_picker_model import parse_start_fields
        run_at = parse_start_fields("2026-11-05", "09:30:15")
        argv = self.build(run_at=run_at)
        self.assertEqual(argv[argv.index("--run-at") + 1], "2026-11-05T09:30:15+08:00")
        self.assertNotIn("--now", argv)

    def test_immediate_and_custom_start_are_mutually_exclusive(self):
        from ncl_openlab_picker_model import parse_start_fields
        with self.assertRaises(ValueError):
            self.build(immediate=True, run_at=parse_start_fields("2026-11-05", "00:00:00"))
        with self.assertRaises(ValueError):
            self.build(run_at=datetime(2026, 11, 5, 0, 0))   # naive: ambiguous timezone

    def test_every_gui_option_reaches_the_engine_parser(self):
        import ncl_openlab_autobook as engine
        from ncl_openlab_picker_model import parse_start_fields
        argv = self.build(room="p03", slots=["14:00-15:00", "13:00-14:00"], accept_terms=True,
                          sync_clock=True, machine_status=True,
                          run_at=parse_start_fields("2026-11-05", "00:00:07"))
        args = engine.build_parser().parse_args(argv)
        self.assertEqual((args.room, args.slots, args.run_at), ("p03", "14:00-15:00,13:00-14:00",
                                                                "2026-11-05T00:00:07+08:00"))
        self.assertTrue(all((args.reserve_two, args.accept_terms,
                             args.sync_clock, args.machine_status, args.auto_submit)))
        self.assertFalse(args.ack_room_unverified)
        self.assertFalse(args.now)

    def test_start_fields_parse_strictly_in_taipei_time(self):
        from ncl_openlab_picker_model import default_run_at_text, parse_start_fields, start_notes
        self.assertEqual(default_run_at_text(date(2026, 11, 12)), "2026-11-05 00:00:00")
        self.assertEqual(parse_start_fields(" 2026-11-05 ", " 23:59:59 ").isoformat(),
                         "2026-11-05T23:59:59+08:00")
        for bad in (("2026-11-05", "9:5"), ("11/05/2026", "00:00:00"), ("", ""), ("2026-11-05", "24:00:00")):
            with self.assertRaises(ValueError):
                parse_start_fields(*bad)
        from ncl_openlab_picker_model import release_datetime
        day = date(2026, 11, 12)
        self.assertIn("預設", start_notes(day, release_datetime(day)))
        self.assertIn("早於", start_notes(day, release_datetime(day) - timedelta(minutes=1)))
        self.assertIn("自訂", start_notes(day, release_datetime(day) + timedelta(minutes=1)))

    def test_validate_start_messages(self):
        from ncl_openlab_picker_model import TAIPEI, parse_start_fields, validate_start
        now = datetime(2026, 11, 4, 12, 0, tzinfo=TAIPEI)
        day = date(2026, 11, 12)
        self.assertIsNone(validate_start(day, parse_start_fields("2026-11-05", "00:00:00"), now))
        self.assertIn("已經過了", validate_start(day, parse_start_fields("2026-11-04", "11:59:59"), now))
        self.assertIn("24 小時", validate_start(day, parse_start_fields("2026-11-06", "12:00:01"), now))
        self.assertIn("預約日", validate_start(day, parse_start_fields("2026-11-13", "00:00:00"), now))

    def test_summary_lines(self):
        from ncl_openlab_picker_model import parse_start_fields, summary_lines
        lines = summary_lines(day=date(2026, 11, 12), room="sewing03", slots=["09:00-10:00"],
                              immediate=False, run_at=parse_start_fields("2026-11-05", "00:00:00"))
        self.assertEqual(len(lines), 4)
        self.assertIn("縫紉機03", lines[0])
        self.assertIn("2026-11-05 00:00:00", lines[3])


if __name__ == "__main__":
    unittest.main()
