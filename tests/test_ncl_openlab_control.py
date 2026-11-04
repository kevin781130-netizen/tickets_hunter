"""GUI <-> engine protocol, one-at-a-time lock, and the run supervisor (real child processes)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import ncl_openlab_control as ctl
from ncl_openlab_schedule import TAIPEI_TZ

STUB = HERE / "fixtures" / "ncl_stub_engine.py"
ARGV = ["--date", "2026-11-12", "--room", "p03", "--slots", "13:00-14:00", "--auto-submit",
        "--run-at", "2026-11-05T00:00:00+08:00", "--machine-status"]


class ProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        event = ctl.parse_event(ctl.encode_event("STANDBY", run_at="2026-11-05T00:00:00+08:00",
                                                  clock_offset=0.4))
        self.assertEqual(event["state"], "STANDBY")
        self.assertEqual(event["clock_offset"], 0.4)

    def test_marker_glued_after_an_unterminated_prompt_is_still_read(self):
        line = "登入及進入頁面後按 Enter 啟動單次自動預約：" + ctl.encode_event("RUNNING")
        self.assertEqual(ctl.parse_event(line)["state"], "RUNNING")

    def test_untrusted_lines_never_raise_or_change_state(self):
        for bad in (None, 5, "", "hello", "@@NCL ", "@@NCL not json", "@@NCL []",
                    '@@NCL {"state": "BOGUS"}', '@@NCL {"no": "state"}'):
            self.assertIsNone(ctl.parse_event(bad), bad)

    def test_fields_are_limited_in_type_and_size(self):
        event = ctl.parse_event('@@NCL {"state": "DONE", "outcome": "' + "x" * 900 +
                                '", "nested": {"a": 1}, "items": [1]}')
        self.assertEqual(len(event["outcome"]), ctl.MAX_FIELD)
        self.assertNotIn("nested", event)
        self.assertNotIn("items", event)

    def test_encoding_an_unknown_state_is_refused(self):
        with self.assertRaises(ValueError):
            ctl.encode_event("PWNED")

    def test_outcomes_map_to_the_right_user_visible_state(self):
        table = {
            "SUCCESS_PAGE_MATCHED": "SUCCESS", "TWO_BOOKINGS_CONFIRMED": "SUCCESS",
            "SUBMITTED_SUCCESS_UNVERIFIED": "UNKNOWN", "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY": "UNKNOWN",
            "SECOND_NOT_CONFIRMED_FAILURE_SHOWN": "UNKNOWN",
            "FIRST_UNVERIFIED_SECOND_NOT_ATTEMPTED_X": "UNKNOWN",
            "PREVIEW_STOPPED_BEFORE_SUBMIT": "FINISHED", "DRY_RUN_COMPLETE": "FINISHED",
            "CANCELLED_BEFORE_START": "CANCELLED", "RUN_AT_MISSED": "FAILED",
            "FAILURE_SHOWN": "FAILED", "RELEASE_REFRESH_BLOCKED_X": "FAILED",
            "RELEASE_WINDOW_EXHAUSTED_NO_BOOKABLE_UI_SLOT": "FAILED", "EXCEPTION_OSError": "FAILED",
            "SOMETHING_NEW": "FAILED",
        }
        for code, state in table.items():
            self.assertEqual(ctl.ui_state_for_outcome(code), state, code)


class RunLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "run.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_holder_is_refused_until_release(self):
        first = ctl.RunLock(self.path, pid=111, alive=lambda pid: True).acquire()
        with self.assertRaises(ctl.RunLockBusy) as ctx:
            ctl.RunLock(self.path, pid=222, alive=lambda pid: True).acquire()
        self.assertEqual(ctx.exception.pid, 111)
        first.release()
        ctl.RunLock(self.path, pid=222, alive=lambda pid: True).acquire().release()
        self.assertFalse(self.path.exists())

    def test_stale_and_corrupt_locks_are_replaced(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"pid": 4242}), encoding="utf-8")
        lock = ctl.RunLock(self.path, pid=1, alive=lambda pid: False).acquire()
        self.assertTrue(lock.held)
        lock.release()
        self.path.write_text("garbage", encoding="utf-8")
        ctl.RunLock(self.path, pid=1, alive=lambda pid: False).acquire().release()

    def test_release_without_holding_never_deletes_someone_elses_lock(self):
        holder = ctl.RunLock(self.path, pid=1, alive=lambda pid: True).acquire()
        ctl.RunLock(self.path, pid=2).release()
        self.assertTrue(self.path.exists())
        holder.release()

    def test_context_manager_releases(self):
        with ctl.RunLock(self.path, alive=lambda pid: True):
            self.assertTrue(self.path.exists())
        self.assertFalse(self.path.exists())

    def test_lock_blocks_a_second_real_process(self):
        code = ("import sys,time; sys.path.insert(0, %r); import ncl_openlab_control as c; "
                "l=c.RunLock(%r).acquire(); print('held', flush=True); time.sleep(5)"
                % (str(HERE.parent / "src"), str(self.path)))
        child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "held")
            with self.assertRaises(ctl.RunLockBusy) as ctx:
                ctl.RunLock(self.path).acquire()
            self.assertEqual(ctx.exception.pid, child.pid)
        finally:
            child.kill()
            child.wait()
        ctl.RunLock(self.path).acquire().release()  # dead owner -> stale -> reusable

    def test_pid_alive(self):
        self.assertTrue(ctl.pid_alive(os.getpid()))
        for bad in (0, -3, None, "12"):
            self.assertFalse(ctl.pid_alive(bad))
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(ctl.pid_alive(child.pid))


class HistoryTests(unittest.TestCase):
    def test_append_read_limit_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h" / "history.jsonl"
            self.assertEqual(ctl.read_history(5, path), [])
            for n in range(5):
                ctl.append_history({"n": n, "bad": object(), "state": "SUCCESS"}, path)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("not json\n")
            rows = ctl.read_history(3, path)
            self.assertEqual([r["n"] for r in rows if "n" in r], [4, 3][:len(rows)] or [])
            self.assertTrue(all("bad" not in r for r in rows))


def pump_until(sup, predicate, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        sup.pump()
        if predicate():
            return True
        time.sleep(0.02)
    sup.pump()
    return predicate()


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sups = []

    def make(self, mode="success", wait="0.6", argv=None, **kwargs):
        env_keys = {"NCL_STUB_MODE": mode, "NCL_STUB_WAIT": wait}
        os.environ.update(env_keys)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in env_keys])
        sup = ctl.RunSupervisor(
            [sys.executable, str(STUB), *(argv or ARGV)],
            meta={"room": "p03", "date": "2026-11-12", "slots": ["13:00-14:00"], "mode": "scheduled"},
            history_path=Path(self.tmp.name) / "history.jsonl",
            lock_path=Path(self.tmp.name) / "run.lock", **kwargs)
        self.sups.append(sup)
        self.addCleanup(lambda: (sup.process and sup.process.poll() is None and sup.process.kill()))
        return sup

    def test_full_happy_path_with_every_visible_state(self):
        sup = self.make()
        seen = []
        sup.start()
        self.assertEqual(sup.state, "LAUNCHING")
        self.assertTrue(pump_until(sup, lambda: sup.state == "LOGIN"))
        seen.append(sup.state)
        self.assertFalse(sup.cancel_requested)
        self.assertTrue(sup.confirm_login())
        self.assertTrue(pump_until(sup, lambda: sup.state == "STANDBY"))
        seen.append(sup.state)
        self.assertIsNotNone(sup.countdown())
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES))
        self.assertEqual((sup.state, sup.outcome), ("SUCCESS", "SUCCESS_PAGE_MATCHED"))
        self.assertEqual(seen, ["LOGIN", "STANDBY"])
        history = ctl.read_history(5, Path(self.tmp.name) / "history.jsonl")
        self.assertEqual((history[0]["state"], history[0]["room"], history[0]["slots"]),
                         ("SUCCESS", "p03", ["13:00-14:00"]))

    def test_engine_receives_exactly_the_arguments_that_were_configured(self):
        sup = self.make()
        sup.start()
        pump_until(sup, lambda: any(text.startswith("ARGS") for _, text in sup.log))
        echo = json.loads(next(t for _, t in sup.log if t.startswith("ARGS "))[5:])
        self.assertEqual((echo["room"], echo["date"], echo["slots"], echo["run_at"]),
                         ("p03", "2026-11-12", "13:00-14:00", "2026-11-05T00:00:00+08:00"))
        self.assertEqual((echo["auto_submit"], echo["machine_status"]), ("True", "True"))
        sup.cancel()
        pump_until(sup, lambda: sup.state in ctl.FINAL_STATES)

    def test_cancel_at_login_and_during_standby_books_nothing(self):
        for when in ("LOGIN", "STANDBY"):
            sup = self.make(wait="30")
            sup.start()
            pump_until(sup, lambda: sup.state == "LOGIN")
            if when == "STANDBY":
                sup.confirm_login()
                pump_until(sup, lambda: sup.state == "STANDBY")
            self.assertTrue(sup.cancel())
            self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES), when)
            self.assertEqual(sup.state, "CANCELLED", when)
            self.assertNotIn("RUNNING", [text for _, text in sup.log])

    def test_cancel_is_refused_once_booking_is_running(self):
        sup = self.make(wait="0.2")
        sup.start()
        pump_until(sup, lambda: sup.state == "LOGIN")
        sup.confirm_login()
        self.assertTrue(pump_until(sup, lambda: sup.state == "RUNNING", 10) or sup.state in ctl.FINAL_STATES)
        if sup.state == "RUNNING":
            self.assertFalse(sup.cancel())

    def test_double_start_is_refused_while_active(self):
        sup = self.make(wait="30")
        sup.start()
        with self.assertRaises(ctl.DuplicateStart):
            sup.start()
        sup.cancel()
        pump_until(sup, lambda: sup.state in ctl.FINAL_STATES)

    def test_a_lock_held_by_another_live_process_blocks_start(self):
        sup = self.make()
        lock = ctl.RunLock(Path(self.tmp.name) / "run.lock", pid=os.getpid()).acquire()
        try:
            with self.assertRaises(ctl.DuplicateStart):
                sup.start()
        finally:
            lock.release()

    def test_unknown_and_failed_outcomes_are_not_reported_as_success(self):
        for mode, state in (("unknown", "UNKNOWN"), ("fail", "FAILED"), ("partial", "UNKNOWN"),
                            ("two", "SUCCESS")):
            sup = self.make(mode=mode, wait="0.2")
            sup.start()
            pump_until(sup, lambda: sup.state == "LOGIN")
            sup.confirm_login()
            self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES), mode)
            self.assertEqual(sup.state, state, mode)

    def test_engine_dying_mid_booking_is_unknown_never_success_or_retry(self):
        sup = self.make(mode="crash_running", wait="0.2")
        sup.start()
        pump_until(sup, lambda: sup.state == "LOGIN")
        sup.confirm_login()
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES))
        self.assertEqual((sup.state, sup.outcome), ("UNKNOWN", "PROCESS_EXITED_DURING_BOOKING"))

    def test_engine_dying_before_standby_is_an_error(self):
        sup = ctl.RunSupervisor([sys.executable, "-c", "import sys; sys.exit(5)"],
                                history_path=Path(self.tmp.name) / "h.jsonl",
                                lock_path=Path(self.tmp.name) / "l.lock")
        sup.start()
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES))
        self.assertEqual((sup.state, sup.outcome), ("ERROR", "PROCESS_EXIT_5"))

    def test_garbage_output_cannot_corrupt_the_state_machine(self):
        sup = self.make(mode="garbage", wait="0.3")
        sup.start()
        pump_until(sup, lambda: sup.state == "LOGIN")
        sup.confirm_login()
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES))
        self.assertEqual(sup.state, "SUCCESS")

    def test_countdown_follows_the_engine_clock_offset(self):
        now = datetime(2026, 11, 4, 23, 59, 0, tzinfo=TAIPEI_TZ)
        sup = self.make(now=lambda: now)
        sup.state, sup.run_at, sup.clock_offset = "STANDBY", now + timedelta(seconds=75), 0.0
        self.assertEqual((sup.countdown(), sup.countdown_text()), (75.0, "00:01:15"))
        sup.clock_offset = 5.0   # engine clock is 5 s ahead of this machine -> fires 5 s sooner
        self.assertEqual(sup.countdown(), 70.0)
        sup.state = "LOGIN"
        self.assertIsNone(sup.countdown())

    def test_force_stop_ends_a_stuck_engine(self):
        sup = self.make(wait="60")
        sup.start()
        pump_until(sup, lambda: sup.state == "LOGIN")
        sup.force_stop()
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES))
        self.assertEqual(sup.state, "ERROR")


if __name__ == "__main__":
    unittest.main()
