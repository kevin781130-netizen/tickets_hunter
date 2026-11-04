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
sys.path.insert(0, str(HERE))

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
    import ncl_openlab_auth as au
    import ncl_openlab_credentials as cred
    from test_ncl_openlab_credentials import FailLikeBackend, MemoryBackend

STUB = HERE / "fixtures" / "ncl_stub_engine.py"
NOW = datetime(2026, 11, 4, 12, 0, 0, tzinfo=TAIPEI_TZ)


def stub_command(argv, executable=None):
    return [sys.executable, str(STUB), *argv]


class WindowHelpers:
    """make/pump/configure for tests that drive the real window."""

    def make(self, *, now=None, mode="success", wait="0.5", store=None, site=None, auth=None):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = {"NCL_STUB_MODE": mode, "NCL_STUB_WAIT": wait}
        if auth:
            env["NCL_STUB_AUTH"] = auth
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        win = picker_mod.BookingPicker(
            history_path=Path(tmp.name) / "history.jsonl", lock_path=Path(tmp.name) / "run.lock",
            now=now or (lambda: NOW), command_builder=stub_command,
            credential_store=store or cred.CredentialStore(MemoryBackend()), site=site)
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
        category = picker_mod.category_for_room(room)
        win.category_box.current(list(picker_mod.CATEGORY_CHOICES).index(category))
        win._category_selected()
        win.room_box.current(picker_mod.room_keys_for_category(category).index(room))
        win._room_selected()
        for slot in slots:
            win._toggle_slot(slot)
        if start is not None:
            win.start_date.set(start.strftime("%Y-%m-%d"))
            win.start_time.set(start.strftime("%H:%M:%S"))
            win._start_typed()
        win.authorize_submit.set(authorize)
        win._refresh_all()



@unittest.skipUnless(TK_OK, TK_WHY)
class PickerWindowTests(WindowHelpers, unittest.TestCase):
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
        self.assertEqual(list(win.category_box.cget("values")), list(picker_mod.CATEGORY_CHOICES.values()))
        self.assertEqual(len(win.category_box.cget("values")), 14)
        self.assertEqual(len(win.room_box.cget("values")), 1)  # default music
        win.category_box.current(list(picker_mod.CATEGORY_CHOICES).index("sewing"))
        win._category_selected()
        self.assertEqual(len(win.room_box.cget("values")), 9)
        win.category_box.current(list(picker_mod.CATEGORY_CHOICES).index("digital_pc"))
        win._category_selected()
        self.assertEqual(len(win.room_box.cget("values")), 10)
        self.assertFalse(win.start_button.enabled)
        self.assertIn("NOT_VERIFIED", win.slot_note.cget("text"))
        win.category_box.current(list(picker_mod.CATEGORY_CHOICES).index("personal_stream"))
        win._category_selected()
        self.assertEqual(len(win.room_box.cget("values")), 3)
        win.room_box.current(1)
        win._room_selected()
        self.assertEqual(win._room_key(), "p01")
        self.assertFalse(win.start_button.enabled)
        self.assertEqual(win.slots, [])
        win.category_box.current(list(picker_mod.CATEGORY_CHOICES).index("language"))
        win._category_selected()
        self.assertEqual(len(win.room_box.cget("values")), 0)
        self.assertIn("僅供現場借用", win.room_note.cget("text"))
        self.assertFalse(win.start_button.enabled)

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
class LoginPanelTests(WindowHelpers, unittest.TestCase):
    """Credential box, login status and the auth flags (inherits the window helpers)."""

    def fillable_site(self):
        return au.load_site()             # the inventoried login form

    def unconfigured_site(self):
        site = au.load_site()
        site["login"] = {**site["login"], "path": None, "account_selector": None,
                         "password_selector": None, "captcha_selector": None, "fields": None}
        return site

    def test_password_box_is_masked_and_saving_never_keeps_the_password(self):
        store = cred.CredentialStore(MemoryBackend())
        win = self.make(store=store)
        self.assertEqual(win.password_entry.cget("show"), "●")
        win.card_var.set("A123456789")
        win.password_var.set("pw-Secret-1")
        win._save_credentials()
        self.assertEqual(store.load(), ("A123456789", "pw-Secret-1"))
        self.assertEqual((win.password_var.get(), win.card_var.get()), ("", ""))
        self.assertIn("A1****89", win.cred_status.cget("text"))
        self.assertNotIn("pw-Secret-1", win.cred_status.cget("text") + win.summary.cget("text"))
        self.assertEqual(self.dialogs[-1][0], "showinfo")

    def test_bad_input_and_insecure_backends_are_refused_and_the_password_is_cleared(self):
        win = self.make(store=cred.CredentialStore(MemoryBackend()))
        win.card_var.set("A123456789")
        win.password_var.set("")
        win._save_credentials()
        self.assertEqual(self.dialogs[-1][0], "showwarning")
        win = self.make(store=cred.CredentialStore(FailLikeBackend()))
        win.card_var.set("A123456789")
        win.password_var.set("pw-Secret-1")
        win._save_credentials()
        self.assertIn("沒有可用的安全金鑰庫", self.dialogs[-1][2])
        self.assertEqual(win.password_var.get(), "")
        self.assertIn("無法儲存", win.cred_status.cget("text"))

    def test_delete_asks_first_and_removes_everything(self):
        store = cred.CredentialStore(MemoryBackend())
        store.save("A123456789", "pw-Secret-1")
        win = self.make(store=store)
        self.assertIn("已安全儲存", win.cred_status.cget("text"))
        self.confirm = False
        win._delete_credentials()
        self.assertTrue(store.has_saved())
        self.confirm = True
        win._delete_credentials()
        self.assertFalse(store.has_saved())
        self.assertIn("尚未儲存", win.cred_status.cget("text"))

    def test_saved_login_option_is_unavailable_while_the_login_form_is_unconfigured(self):
        store = cred.CredentialStore(MemoryBackend())
        store.save("A123456789", "pw-Secret-1")
        win = self.make(store=store, site=self.unconfigured_site())
        self.assertEqual(str(win.saved_login_check.cget("state")), "disabled")
        self.assertIn("NOT_VERIFIED", win.saved_login_note.cget("text"))
        self.assertFalse(win.use_saved_login.get())

    def test_saved_login_option_needs_saved_credentials_and_verified_fields(self):
        store = cred.CredentialStore(MemoryBackend())
        win = self.make(store=store, site=self.fillable_site())
        self.assertEqual(str(win.saved_login_check.cget("state")), "disabled")      # nothing saved
        store.save("A123456789", "pw-Secret-1")
        win._refresh_credentials()
        self.assertEqual(str(win.saved_login_check.cget("state")), "normal")
        self.assertIn("尚待實機驗證", win.saved_login_note.cget("text"))

    def test_start_passes_auth_flags_but_never_the_password(self):
        store = cred.CredentialStore(MemoryBackend())
        store.save("A123456789", "pw-Secret-1")
        win = self.make(store=store, site=self.fillable_site(), auth="LOGIN_SUCCESS", wait="0.3")
        self.configure(win, start=NOW + timedelta(minutes=5))
        win.use_saved_login.set(True)
        win._start()
        sup = win.supervisor
        self.assertIn("--auth-check", sup.argv)
        self.assertIn("--use-saved-login", sup.argv)
        self.assertNotIn("pw-Secret-1", " ".join(sup.argv))
        self.assertNotIn("A123456789", " ".join(sup.argv))
        self.assertTrue(self.pump(win, lambda: sup.state in ctl.FINAL_STATES, 20))

    def test_without_the_option_the_saved_login_flag_is_not_passed(self):
        win = self.make(auth="LOGIN_SUCCESS", wait="0.3")
        self.configure(win, start=NOW + timedelta(minutes=5))
        win._start()
        self.assertIn("--auth-check", win.supervisor.argv)
        self.assertNotIn("--use-saved-login", win.supervisor.argv)
        self.pump(win, lambda: win.supervisor.state in ctl.FINAL_STATES, 20)

    def test_login_status_is_shown_and_the_manual_button_is_only_a_fallback(self):
        win = self.make(auth="CAPTCHA_WAITING", wait="1.5")
        self.configure(win, start=NOW + timedelta(minutes=5))
        win._start()
        sup = win.supervisor
        self.assertTrue(self.pump(win, lambda: sup.auth_state == "CAPTCHA_WAITING"))
        self.assertIn("輸入圖片驗證碼", win.auth_label.cget("text"))
        self.assertEqual(sup.state, "LOGIN")
        self.assertFalse(win.login_button.enabled, "no manual button while a CAPTCHA is expected")
        self.assertTrue(self.pump(win, lambda: sup.auth_state == "LOGIN_SUCCESS"))
        self.assertIn("登入成功", win.auth_label.cget("text"))
        self.pump(win, lambda: sup.state in ctl.FINAL_STATES, 20)

    def test_manual_confirmation_button_appears_for_inconclusive_pages(self):
        win = self.make(auth="AUTH_INTERACTION_REQUIRED")
        self.configure(win, start=NOW + timedelta(minutes=5))
        win._start()
        sup = win.supervisor
        self.assertTrue(self.pump(win, lambda: sup.auth_state == "AUTH_INTERACTION_REQUIRED"))
        self.assertTrue(win.login_button.enabled)
        win._confirm_login()
        self.assertTrue(self.pump(win, lambda: sup.auth_state == "LOGIN_SUCCESS"))
        self.pump(win, lambda: sup.state in ctl.FINAL_STATES, 20)

    def test_terms_checkbox_explains_the_version_rule(self):
        import inspect
        source = inspect.getsource(picker_mod.BookingPicker._build)
        self.assertIn("同一版本", source)
        self.assertIn("重新同意", source)


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
