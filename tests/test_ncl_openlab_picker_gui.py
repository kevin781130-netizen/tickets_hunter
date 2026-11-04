"""The real Tk window (needs tkinter and a display, e.g. xvfb-run); skipped otherwise."""
import os
import sys
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    TK_OK, TK_WHY = True, ""
except Exception as exc:  # no tkinter, or no display
    TK_OK, TK_WHY = False, f"NOT_RUN: Tk unavailable ({type(exc).__name__})"

from ncl_openlab_schedule import TAIPEI_TZ

if TK_OK:
    import ncl_openlab_picker as picker_mod
    import ncl_openlab_control as ctl

STUB = HERE / "fixtures" / "ncl_stub_engine.py"
NOW = datetime(2026, 11, 4, 12, 0, 0, tzinfo=TAIPEI_TZ)


def stub_command(argv, executable=None):
    return [sys.executable, str(STUB), *argv]


@unittest.skipUnless(TK_OK, TK_WHY)
class PickerWindowTests(unittest.TestCase):
    def make(self, *, now=None, mode="success", wait="0.5"):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.dict(os.environ, {"NCL_STUB_MODE": mode, "NCL_STUB_WAIT": wait})
        patcher.start()
        self.addCleanup(patcher.stop)
        win = picker_mod.BookingPicker(
            history_path=Path(tmp.name) / "history.jsonl", lock_path=Path(tmp.name) / "run.lock",
            now=now or (lambda: NOW), command_builder=stub_command)
        self.addCleanup(lambda: (win.supervisor and win.supervisor.process
                                 and win.supervisor.process.poll() is None
                                 and win.supervisor.process.kill()))
        self.addCleanup(win.destroy)
        self.dialogs = []
        for name in ("showwarning", "showerror", "showinfo"):
            patcher = patch.object(picker_mod.messagebox, name,
                                   lambda title, text, n=name, **k: self.dialogs.append((n, title, text)))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.confirm = True
        patcher = patch.object(picker_mod.messagebox, "askyesno",
                               lambda title, text, **k: (self.dialogs.append(("askyesno", title, text)),
                                                         self.confirm)[1])
        patcher.start()
        self.addCleanup(patcher.stop)
        return win

    def pump(self, win, predicate, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            win.update()
            if predicate():
                return True
            time.sleep(0.02)
        win.update()
        return predicate()

    def configure(self, win, *, room="p03", slots=("13:00-14:00",), start=None, authorize=True):
        win.room.set(room)
        win.room_box.current(list(picker_mod.ROOM_CHOICES).index(room))
        win._room_selected()
        for slot in slots:
            win._toggle_slot(slot)
        if start is not None:
            win.start_date.set(start.strftime("%Y-%m-%d"))
            win.start_time.set(start.strftime("%H:%M:%S"))
            win._start_typed()
        win.authorize_submit.set(authorize)
        win._refresh_all()

    # ------------------------------------------------------------- defaults
    def test_default_start_is_seven_days_before_midnight_and_editable(self):
        win = self.make()
        self.assertEqual(win.selected_date.isoformat(), "2026-11-12")
        self.assertEqual((win.start_date.get(), win.start_time.get()), ("2026-11-05", "00:00:00"))
        self.assertIn("預設", win.start_note.cget("text"))
        win.start_time.set("09:30:15")
        win._start_typed()
        self.assertNotIn("預設", win.start_note.cget("text"))
        win._pick_date(win.selected_date + timedelta(days=1))
        self.assertEqual(win.start_time.get(), "09:30:15", "a user-edited start must survive date changes")
        self.assertEqual(win.start_date.get(), "2026-11-05")
        win._reset_start_time()
        self.assertEqual((win.start_date.get(), win.start_time.get()), ("2026-11-06", "00:00:00"))

    def test_changing_date_moves_the_untouched_default_start(self):
        win = self.make()
        win._pick_date(win.selected_date + timedelta(days=3))
        self.assertEqual(win.start_date.get(), "2026-11-08")

    def test_summary_lists_room_date_slots_and_start(self):
        win = self.make()
        self.configure(win, room="p03", slots=("14:00-15:00", "13:00-14:00"))
        text = win.summary.cget("text")
        for expected in ("P03 個人直播室", "2026-11-12", "14:00-15:00 → 13:00-14:00",
                         "2026-11-05 00:00:00（台北時間）開始預約"):
            self.assertIn(expected, text)
        win.mode.set("now")
        win._refresh_all()
        self.assertIn("立即執行", win.summary.cget("text"))
        self.assertEqual(win.start_button.cget("text"), "立即執行")
        self.assertEqual(str(win.time_entry.cget("state")), "disabled")

    # ------------------------------------------------------------ validation
    def test_invalid_or_past_or_late_start_blocks_launch(self):
        win = self.make()
        self.configure(win)
        win.start_date.set("2026-11-05")
        win.start_time.set("25:61:00")
        win._start_typed()
        win._start()
        self.assertIsNone(win.supervisor)
        self.assertIn("格式", self.dialogs[-1][2])
        win.start_date.set("2026-11-04")
        win.start_time.set("11:59:59")      # one second in the past
        win._start()
        self.assertIn("已經過了", self.dialogs[-1][2])
        win.start_date.set("2026-11-13")
        win.start_time.set("00:00:00")      # after the target day
        win._start()
        self.assertIn("不可晚於預約日", self.dialogs[-1][2])
        win.start_date.set("2026-11-06")
        win.start_time.set("00:00:00")      # more than 24 h ahead
        win._start()
        self.assertIn("24 小時", self.dialogs[-1][2])
        self.assertIsNone(win.supervisor)

    def test_submit_authorisation_and_slot_selection_are_required(self):
        win = self.make()
        self.configure(win, slots=("13:00-14:00",), authorize=False,
                       start=NOW + timedelta(minutes=5))
        win._start()
        self.assertIn("授權", self.dialogs[-1][2])
        win.authorize_submit.set(True)
        win._clear_slots()
        win._start()
        self.assertIn("時段", self.dialogs[-1][2])
        self.assertIsNone(win.supervisor)

    def test_at_most_two_slots_and_order_is_the_booking_order(self):
        win = self.make()
        self.configure(win, slots=("15:00-16:00", "13:00-14:00"))
        win._toggle_slot("14:00-15:00")
        self.assertEqual(win.slots, ["15:00-16:00", "13:00-14:00"])
        self.assertEqual(self.dialogs[-1][0], "showwarning")
        win._toggle_slot("15:00-16:00")
        self.assertEqual(win.slots, ["13:00-14:00"])

    def test_unverified_equipment_shows_and_requires_its_own_acknowledgement(self):
        win = self.make()
        self.configure(win, room="sewing01", start=NOW + timedelta(minutes=5))
        win.update()
        self.assertTrue(win.ack_check.winfo_manager())
        self.assertIn("尚未實機驗證", win.room_note.cget("text"))
        win._start()
        self.assertIn("尚未實機驗證", self.dialogs[-1][2])
        self.assertIsNone(win.supervisor)
        # switching back to a verified room hides the acknowledgement again
        self.configure(win, room="p03", slots=("13:00-14:00",))
        win.update()
        self.assertFalse(win.ack_check.winfo_manager())

    def test_room_list_comes_from_the_config(self):
        win = self.make()
        self.assertEqual(list(win.room_box.cget("values")), list(picker_mod.ROOM_CHOICES.values()))
        self.assertEqual(len(win.room_box.cget("values")), 11)

    # ---------------------------------------------------------------- runs
    def test_start_wires_every_setting_into_the_engine_and_tracks_each_state(self):
        win = self.make(wait="0.4")
        start = datetime.now(TAIPEI_TZ) + timedelta(seconds=60)
        win._now = lambda: datetime.now(TAIPEI_TZ)
        win.selected_date = (start + timedelta(days=7)).date()
        self.configure(win, room="p03", slots=("14:00-15:00", "13:00-14:00"),
                       start=start.replace(microsecond=0))
        win.accept_terms.set(True)
        win.sync_clock.set(False)
        win._start()
        self.assertEqual(self.dialogs[-1][0], "askyesno")
        self.assertIn("將正式預約", self.dialogs[-1][2])
        sup = win.supervisor
        self.assertTrue(self.pump(win, lambda: sup.state == "LOGIN"))
        self.assertEqual(win.state_label.cget("text"), ctl.STATE_LABELS["LOGIN"])
        self.assertTrue(win.login_button.enabled)
        self.assertFalse(win.start_button.enabled, "duplicate start must be blocked while active")
        self.assertTrue(win.cancel_button.enabled)
        win._start()                                          # duplicate click
        self.assertIs(win.supervisor, sup)
        self.assertIn("已在執行", self.dialogs[-1][1])
        # the stub echoes what the real parser received: GUI settings reached the engine
        self.pump(win, lambda: any(t.startswith("ARGS") for _, t in sup.log))
        import json
        echo = json.loads(next(t for _, t in sup.log if t.startswith("ARGS "))[5:])
        self.assertEqual((echo["room"], echo["slots"], echo["reserve_two"], echo["machine_status"]),
                         ("p03", "14:00-15:00,13:00-14:00", "True", "True"))
        self.assertEqual(echo["run_at"], start.replace(microsecond=0).isoformat())
        win._confirm_login()
        self.assertTrue(self.pump(win, lambda: sup.state == "STANDBY"))
        self.assertIn("後開始預約", win.countdown_label.cget("text"))
        self.assertFalse(win.login_button.enabled)
        self.assertTrue(self.pump(win, lambda: sup.state == "SUCCESS", 20))
        self.assertEqual(win.state_label.cget("text"), ctl.STATE_LABELS["SUCCESS"])
        self.assertTrue(win.start_button.enabled)
        self.assertIn("預約成功", win.log_box.get("1.0", "end"))
        self.assertEqual(win.history_box.size(), 1)

    def test_cancel_returns_to_idle_and_allows_a_new_start(self):
        win = self.make(wait="60")
        self.configure(win, start=NOW + timedelta(minutes=5))
        win._now = lambda: NOW
        win._start()
        sup = win.supervisor
        self.pump(win, lambda: sup.state == "LOGIN")
        win._confirm_login()
        self.pump(win, lambda: sup.state == "STANDBY")
        win._cancel()
        self.assertTrue(self.pump(win, lambda: sup.state == "CANCELLED"))
        self.assertTrue(win.start_button.enabled)
        self.assertFalse(win.cancel_button.enabled)
        self.assertEqual(win.countdown_label.cget("text"), "")
        self.assertEqual(win.history_box.size(), 1)

    def test_unknown_result_is_shown_as_unknown(self):
        win = self.make(mode="unknown", wait="0.3")
        self.configure(win, start=NOW + timedelta(minutes=5))
        win._start()
        sup = win.supervisor
        self.pump(win, lambda: sup.state == "LOGIN")
        win._confirm_login()
        self.assertTrue(self.pump(win, lambda: sup.state == "UNKNOWN", 20))
        self.assertIn("勿重送", win.state_label.cget("text"))

    def test_settings_are_locked_while_a_run_is_active(self):
        win = self.make(wait="60")
        self.configure(win, start=NOW + timedelta(minutes=5))
        win._start()
        sup = win.supervisor
        self.pump(win, lambda: sup.state == "LOGIN")
        before = (win.selected_date, list(win.slots), win.room.get())
        win._pick_date(win.selected_date + timedelta(days=2))
        win._toggle_slot("15:00-16:00")
        win._clear_slots()
        self.assertEqual((win.selected_date, list(win.slots), win.room.get()), before)
        self.assertEqual(str(win.room_box.cget("state")), "disabled")
        win._cancel()
        self.pump(win, lambda: sup.state == "CANCELLED")

    def test_closing_the_window_never_interrupts_a_running_booking(self):
        win = self.make()
        self.configure(win, start=NOW + timedelta(minutes=5))
        win.supervisor = ctl.RunSupervisor(["x"], lock_path=Path("/nonexistent/l"))
        win.supervisor.state = "RUNNING"
        with patch.object(win, "destroy") as destroy:
            win._on_close()
            destroy.assert_not_called()
        self.assertEqual(self.dialogs[-1][1], "預約進行中")
        win.supervisor.state = "IDLE"

    def test_closing_during_standby_asks_and_cancels(self):
        win = self.make(wait="60")
        self.configure(win, start=NOW + timedelta(minutes=5))
        win._start()
        sup = win.supervisor
        self.pump(win, lambda: sup.state == "LOGIN")
        win._confirm_login()
        self.pump(win, lambda: sup.state == "STANDBY")
        self.confirm = False
        with patch.object(win, "destroy") as destroy:
            win._on_close()
            destroy.assert_not_called()
            self.confirm = True
            win._on_close()
            destroy.assert_called_once()
        self.assertTrue(sup.cancel_requested)
        self.pump(win, lambda: sup.state == "CANCELLED")


@unittest.skipUnless(TK_OK, TK_WHY)
class WidgetTests(unittest.TestCase):
    def test_flat_button_respects_enabled_state(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        calls = []
        button = picker_mod.FlatButton(root, "x", lambda: calls.append(1))
        button.invoke()
        button.set_enabled(False)
        button.invoke()
        button.set_enabled(True)
        button.invoke()
        self.assertEqual(len(calls), 2)

    def test_fonts_follow_the_platform(self):
        for platform, family in (("darwin", "PingFang TC"), ("win32", "Microsoft JhengHei UI"),
                                 ("linux", "sans-serif")):
            with patch.object(picker_mod.sys, "platform", platform):
                self.assertEqual(picker_mod.ui_font(10)[0], family)
        self.assertEqual(picker_mod.ui_font(12, True)[2], "bold")


if __name__ == "__main__":
    unittest.main()
