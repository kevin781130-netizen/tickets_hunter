"""End to end: GUI argument builder -> supervisor -> REAL engine -> fake browser.

Real wall-clock, real child processes, real CLI parsing and the real Timeline.
Only Chrome/zendriver is replaced. Proves the schedule is not just a display:
the booking operations begin at the configured second, and not before.
"""
import json
import math
import os
import re
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import ncl_openlab_control as ctl
from ncl_openlab_picker_model import build_booking_args
from ncl_openlab_schedule import TAIPEI_TZ

FAKE = HERE / "fixtures" / "ncl_fake_browser_engine.py"
DAY = date(2026, 11, 12)
TOLERANCE = 0.15


def soon(seconds):
    """A start time on a whole second, at least ``seconds`` from now (Taipei)."""
    target = datetime.now(TAIPEI_TZ) + timedelta(seconds=seconds)
    return (target + timedelta(seconds=1 - target.microsecond / 1e6)).replace(microsecond=0)


def pump_until(sup, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        sup.pump()
        if predicate():
            return True
        time.sleep(0.02)
    sup.pump()
    return predicate()


class Harness:
    def __init__(self, test, **env):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.events = self.dir / "events.jsonl"
        self.lock = self.dir / "run.lock"
        self.env = {"NCL_FAKE_EVENTS": str(self.events), "NCL_LOCK_PATH": str(self.lock), **env}
        patcher = patch.dict(os.environ, self.env)
        patcher.start()
        test.addCleanup(patcher.stop)
        self.test = test

    def supervisor(self, **kwargs):
        kwargs.setdefault("slots", ["13:00-14:00"])
        kwargs.setdefault("room", "p03")
        extra = {k: kwargs.pop(k) for k in list(kwargs) if k in ("report_dir",)}
        argv = build_booking_args(day=DAY, auto_submit=True, machine_status=True, **kwargs)
        if extra.get("report_dir"):
            argv += ["--report-dir", extra["report_dir"]]
        sup = ctl.RunSupervisor([sys.executable, str(FAKE), *argv],
                                meta={"room": kwargs["room"], "date": DAY.isoformat(),
                                      "slots": kwargs["slots"]},
                                history_path=self.dir / "history.jsonl", lock_path=self.lock)
        self.test.addCleanup(lambda: sup.process and sup.process.poll() is None and sup.process.kill())
        return sup

    def login(self, sup):
        sup.start()
        self.test.assertTrue(pump_until(sup, lambda: sup.state == "LOGIN", 20), sup.log)
        sup.confirm_login()

    def read(self):
        if not self.events.exists():
            return []
        return [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]

    def times(self, kind, **match):
        return [e["t"] for e in self.read() if e["kind"] == kind
                and all(e.get(k) == v for k, v in match.items())]


class ScheduledStartTests(unittest.TestCase):
    def test_booking_operations_begin_at_the_configured_second_and_not_before(self):
        h = Harness(self)
        run_at = soon(6)
        sup = h.supervisor(run_at=run_at)
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state == "STANDBY", 10), sup.log)
        self.assertEqual(sup.run_at, run_at)
        self.assertGreater(sup.countdown(), 0)
        self.assertEqual(h.times("phase"), [], "nothing may be clicked during standby")
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 30), sup.log)
        self.assertEqual((sup.state, sup.outcome), ("SUCCESS", "SUCCESS_PAGE_MATCHED"))
        target = run_at.timestamp()
        first_phase = min(h.times("phase"))
        self.assertGreaterEqual(first_phase, target - TOLERANCE)
        self.assertLess(first_phase, target + 3)
        self.assertGreaterEqual(min(h.times("reload")), target - TOLERANCE)  # refresh at T
        self.assertEqual(len(h.times("submit_keypress")), 1)

    def test_warmup_refresh_ten_seconds_before_and_exact_refresh_at_start(self):
        h = Harness(self)
        run_at = soon(14)
        sup = h.supervisor(run_at=run_at)
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 40), sup.log)
        self.assertEqual(sup.state, "SUCCESS")
        reloads = h.times("reload")
        self.assertEqual(len(reloads), 2)
        target = run_at.timestamp()
        self.assertAlmostEqual(reloads[0], target - 10, delta=0.5)
        self.assertGreaterEqual(reloads[1], target - TOLERANCE)
        self.assertEqual(h.times("phase", phase="date")[0] >= target - TOLERANCE, True)

    def test_two_slots_are_booked_one_after_the_other_each_submitted_once(self):
        h = Harness(self)
        sup = h.supervisor(run_at=soon(5), slots=["13:00-14:00", "14:00-15:00"])
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 40), sup.log)
        self.assertEqual((sup.state, sup.outcome), ("SUCCESS", "TWO_BOOKINGS_CONFIRMED"))
        phases = [(e["phase"], e["slot"]) for e in h.read() if e["kind"] == "phase"]
        self.assertEqual([s for p, s in phases if p == "submit"], ["13:00-14:00", "14:00-15:00"])
        self.assertEqual(len(h.times("submit_keypress")), 2)
        self.assertEqual(len(h.times("navigate")), 1)   # re-entry between the two bookings
        first_success = h.times("phase", phase="success", slot="13:00-14:00")[0]
        self.assertLess(first_success, h.times("phase", phase="date", slot="14:00-15:00")[0])

    def test_unverified_result_is_unknown_and_is_never_submitted_again(self):
        h = Harness(self, NCL_FAKE_RESULT="unverified")
        sup = h.supervisor(run_at=soon(5))
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 40), sup.log)
        self.assertEqual((sup.state, sup.outcome), ("UNKNOWN", "SUBMITTED_SUCCESS_UNVERIFIED"))
        self.assertEqual(len(h.times("submit_keypress")), 1)

    def test_a_failure_page_is_reported_and_not_retried(self):
        h = Harness(self, NCL_FAKE_RESULT="failure")
        sup = h.supervisor(run_at=soon(5))
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 40), sup.log)
        self.assertEqual((sup.state, sup.outcome), ("FAILED", "FAILURE_SHOWN"))
        self.assertEqual(len(h.times("submit_keypress")), 1)

    def test_immediate_mode_starts_right_after_login(self):
        h = Harness(self)
        sup = h.supervisor(immediate=True)
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 30), sup.log)
        self.assertEqual(sup.state, "SUCCESS")
        self.assertEqual(h.times("reload"), [], "no release refresh in immediate mode")
        self.assertNotIn("STANDBY", [t for _, t in sup.log])

    def test_report_records_the_custom_start_time(self):
        h = Harness(self)
        run_at = soon(5)
        sup = h.supervisor(run_at=run_at, report_dir=str(h.dir / "reports"))
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 30), sup.log)
        report = json.loads(next((h.dir / "reports").glob("ncl_run_*.json")).read_text(encoding="utf-8"))
        self.assertEqual(report["schedule"]["run_at"], run_at.isoformat())
        self.assertEqual(report["outcome"]["category"], "SUCCESS_CONFIRMED")


class SafetyTests(unittest.TestCase):
    def test_cancel_during_standby_never_touches_the_booking_site(self):
        h = Harness(self)
        sup = h.supervisor(run_at=soon(90))
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state == "STANDBY", 10), sup.log)
        self.assertTrue(sup.cancel())
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 15), sup.log)
        self.assertEqual((sup.state, sup.outcome), ("CANCELLED", "CANCELLED_BEFORE_START"))
        self.assertEqual(h.times("phase"), [])
        self.assertEqual(h.times("reload"), [])
        self.assertFalse(h.lock.exists(), "lock must be released")

    def test_a_past_start_time_is_refused_by_the_engine_itself(self):
        h = Harness(self)
        past = datetime.now(TAIPEI_TZ) - timedelta(minutes=5)
        argv = build_booking_args(day=DAY, room="p03", slots=["13:00-14:00"], auto_submit=True,
                                  run_at=past, machine_status=True)
        import subprocess
        done = subprocess.run([sys.executable, str(FAKE), *argv], capture_output=True, text=True,
                              timeout=30, input="\n")
        self.assertEqual(done.returncode, 2)
        self.assertIn("RUN_AT_ALREADY_PASSED", done.stderr)
        self.assertEqual(h.read(), [])

    def test_a_second_engine_cannot_start_while_one_is_on_standby(self):
        h = Harness(self)
        first = h.supervisor(run_at=soon(90))
        h.login(first)
        self.assertTrue(pump_until(first, lambda: first.state == "STANDBY", 10), first.log)
        argv = build_booking_args(day=DAY, room="p03", slots=["13:00-14:00"], auto_submit=True,
                                  immediate=True, machine_status=True)
        import subprocess
        done = subprocess.run([sys.executable, str(FAKE), *argv], capture_output=True, text=True,
                              timeout=30, input="\n")
        self.assertEqual(done.returncode, 2)
        # On Windows, a non-UTF-8 subprocess stderr may backslash-escape Chinese.
        # Normalize only Unicode escapes; still assert the complete lock message.
        stderr = re.sub(r"\\u([0-9a-fA-F]{4})",
                        lambda match: chr(int(match.group(1), 16)), done.stderr)
        self.assertIn("同一時間只允許一個預約程序", stderr)
        self.assertEqual(h.times("phase"), [])
        first.cancel()
        pump_until(first, lambda: first.state in ctl.FINAL_STATES, 15)

    def test_login_lost_before_the_start_is_reported_and_nothing_is_booked(self):
        h = Harness(self, NCL_FAKE_ENTRY_AFTER_RELOAD="ENTRY_NOT_FOUND_OR_AMBIGUOUS")
        sup = h.supervisor(run_at=soon(13))
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 40), sup.log)
        self.assertEqual(sup.state, "FAILED")
        self.assertEqual(sup.outcome, "PRE_REFRESH_BLOCKED_ENTRY_NOT_FOUND_OR_AMBIGUOUS")
        self.assertEqual(h.times("phase"), [])
        self.assertEqual(h.times("submit_keypress"), [])

    def test_network_down_at_the_start_is_reported_and_nothing_is_booked(self):
        h = Harness(self, NCL_FAKE_RELOAD_ERROR="1")
        sup = h.supervisor(run_at=soon(5))
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 30), sup.log)
        self.assertEqual((sup.state, sup.outcome),
                         ("FAILED", "RELEASE_REFRESH_BLOCKED_REFRESH_FAILED_OSError"))
        self.assertEqual(h.times("phase"), [])

    def test_unverified_equipment_cannot_be_started_even_with_acknowledgement(self):
        with self.assertRaises(ValueError):
            build_booking_args(day=DAY, room="sewing01", slots=["13:00-14:00"], auto_submit=True,
                               immediate=True)
        with self.assertRaisesRegex(ValueError, "NOT_VERIFIED"):
            build_booking_args(day=DAY, room="sewing01", slots=["13:00-14:00"], auto_submit=True,
                               immediate=True, ack_unverified=True, machine_status=True)

    def test_verified_p03_runs_through_shared_hourly_engine(self):
        """Fake browser exercises shared flow; unverified equipment is blocked by GUI model."""
        h = Harness(self)
        sup = h.supervisor(room="p03", immediate=True)
        h.login(sup)
        self.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, 30), sup.log)
        self.assertEqual(sup.state, "SUCCESS")
        phases = {e["phase"] for e in h.read() if e["kind"] == "phase"}
        self.assertEqual(phases, {"date", "room", "slot", "next", "submit", "success"})


if __name__ == "__main__":
    unittest.main()
