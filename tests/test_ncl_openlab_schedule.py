"""Custom start time: parsing, countdown, exact trigger, sleep/jump/cancel, clock sync."""
import asyncio
import socket
import struct
import sys
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import ncl_openlab_autobook as app
import ncl_openlab_schedule as sched
from ncl_fakes import FakeClock, FakeTab

TZ = sched.TAIPEI_TZ
DAY = date(2026, 11, 12)
RELEASE = datetime(2026, 11, 5, 0, 0, 0, tzinfo=TZ)


def run(coro):
    return asyncio.run(coro)


class ParseTests(unittest.TestCase):
    def test_accepted_forms_all_resolve_to_taipei(self):
        same = datetime(2026, 11, 5, 0, 0, 0, tzinfo=TZ)
        for text in ("2026-11-05T00:00:00+08:00", "2026-11-05 00:00:00", "2026-11-05T00:00",
                     "2026-11-04T16:00:00Z", "2026-11-05T01:00:00+09:00", " 2026-11-05 00:00 "):
            self.assertEqual(sched.parse_run_at(text), same, text)
        self.assertEqual(sched.parse_run_at("2026-11-04T16:00:00Z").utcoffset(), timedelta(hours=8))

    def test_seconds_precision_and_microseconds_dropped(self):
        parsed = sched.parse_run_at("2026-11-05T00:00:07.9+08:00")
        self.assertEqual((parsed.second, parsed.microsecond), (7, 0))

    def test_rejects_unreadable_or_date_only_input(self):
        for bad in ("", "  ", None, 5, "2026-11-05", "tomorrow", "2026-13-40 00:00", "00:00:00"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                sched.parse_run_at(bad)

    def test_default_is_seven_days_before_midnight_taipei(self):
        self.assertEqual(sched.release_run_at(DAY), RELEASE)
        self.assertEqual(sched.release_run_at(date(2026, 3, 1)).isoformat(), "2026-02-22T00:00:00+08:00")
        with self.assertRaises(ValueError):
            sched.release_run_at(datetime(2026, 11, 12))
        self.assertEqual(app.release_time(DAY), RELEASE)  # engine uses the same helper

    def test_countdown_text(self):
        self.assertEqual(sched.format_countdown(0), "00:00:00")
        self.assertEqual(sched.format_countdown(-5), "00:00:00")
        self.assertEqual(sched.format_countdown(3661.9), "01:01:01")
        self.assertEqual(sched.format_countdown(2 * 86400 + 5), "2 天 00:00:05")


class CheckRunAtTests(unittest.TestCase):
    NOW = datetime(2026, 11, 4, 22, 0, 0, tzinfo=TZ)

    def check(self, run_at, **kw):
        kw.setdefault("max_wait_seconds", sched.MAX_CUSTOM_WAIT_SECONDS)
        return sched.check_run_at(run_at, self.NOW, DAY, **kw)

    def test_valid_early_start_over_15_minutes_is_allowed(self):
        self.assertIsNone(self.check(RELEASE))           # 2 hours ahead
        self.assertIsNone(self.check(self.NOW + timedelta(seconds=1)))

    def test_past_far_after_target_and_naive_are_refused(self):
        self.assertEqual(self.check(self.NOW - timedelta(seconds=1)), "RUN_AT_ALREADY_PASSED")
        self.assertEqual(self.check(self.NOW + timedelta(hours=25)), "RUN_AT_TOO_FAR")
        self.assertEqual(self.check(datetime(2026, 11, 13, 0, 0, tzinfo=TZ)), "RUN_AT_AFTER_TARGET_DAY")
        self.assertEqual(self.check(datetime(2026, 11, 5, 0, 0)), "RUN_AT_INVALID")
        self.assertEqual(self.check("x"), "RUN_AT_INVALID")

    def test_grace_allows_a_slightly_late_start_only(self):
        late = self.NOW - timedelta(seconds=20)
        self.assertEqual(self.check(late, grace=0), "RUN_AT_ALREADY_PASSED")
        self.assertIsNone(self.check(late, grace=30))

    def test_start_on_the_target_day_itself_is_allowed(self):
        self.assertIsNone(sched.check_run_at(datetime(2026, 11, 12, 23, 0, tzinfo=TZ),
                                             datetime(2026, 11, 12, 22, 0, tzinfo=TZ), DAY,
                                             max_wait_seconds=86400))


class SystemClockTests(unittest.TestCase):
    def test_offset_shifts_now_and_absurd_values_are_refused(self):
        plain, shifted = sched.SystemClock(), sched.SystemClock(2.5)
        delta = (shifted.now() - plain.now()).total_seconds()
        self.assertAlmostEqual(delta, 2.5, delta=0.2)
        self.assertEqual(plain.now().utcoffset(), timedelta(hours=8))
        with self.assertRaises(ValueError):
            sched.SystemClock(601)


class TimelineTests(unittest.TestCase):
    def test_sleep_wakes_exactly_on_target_in_one_second_chunks(self):
        clock = FakeClock(RELEASE - timedelta(seconds=10))
        timeline = sched.Timeline(RELEASE, clock)
        run(timeline.sleep(10))
        self.assertEqual(clock.now(), RELEASE)
        self.assertEqual(clock.sleeps, [1.0] * 10)

    def test_fractional_tail_is_not_overslept(self):
        clock = FakeClock(RELEASE - timedelta(seconds=2.5))
        run(sched.Timeline(RELEASE, clock).sleep(2.5))
        self.assertEqual(clock.sleeps, [1.0, 1.0, 0.5])
        self.assertEqual(clock.now(), RELEASE)

    def test_laptop_sleep_past_the_start_time_raises_missed(self):
        clock = FakeClock(RELEASE - timedelta(seconds=60), jumps={3: 3600})
        timeline = sched.Timeline(RELEASE, clock, grace=30)
        with self.assertRaises(sched.ScheduleMissed):
            run(timeline.sleep(60))
        self.assertEqual(timeline.events[0][0], "CLOCK_JUMP")

    def test_jump_that_still_leaves_time_is_reported_but_not_fatal(self):
        clock = FakeClock(RELEASE - timedelta(seconds=60), jumps={2: 20})
        timeline = sched.Timeline(RELEASE, clock)
        run(timeline.sleep(60))
        self.assertEqual([e[0] for e in timeline.events], ["CLOCK_JUMP"])
        self.assertEqual(clock.now(), RELEASE)

    def test_cancel_stops_waiting_within_one_chunk(self):
        clock = FakeClock(RELEASE - timedelta(seconds=60))
        flag = {"stop": False}

        async def go():
            timeline = sched.Timeline(RELEASE, clock, cancelled=lambda: flag["stop"],
                                      on_event=lambda *a: None)
            original = clock.sleep

            async def sleeping(seconds):
                await original(seconds)
                flag["stop"] = len(clock.sleeps) >= 5
            clock.sleep = sleeping
            await timeline.sleep(60)
        with self.assertRaises(sched.ScheduleCancelled):
            run(go())
        self.assertLessEqual(len(clock.sleeps), 6)

    def test_waiting_across_midnight_uses_wall_time(self):
        start = datetime(2026, 11, 4, 23, 59, 55, tzinfo=TZ)
        clock = FakeClock(start)
        timeline = sched.Timeline(datetime(2026, 11, 5, 0, 0, 3, tzinfo=TZ), clock)
        run(timeline.sleep(timeline.remaining()))
        self.assertEqual(clock.now().isoformat(), "2026-11-05T00:00:03+08:00")


class WaitUntilStartTests(unittest.TestCase):
    """The engine's wait: T-10 warm-up, exact T refresh, no booking before."""

    def wait(self, now, run_at, *, tab_kwargs=None, clock_kwargs=None, **kwargs):
        clock = FakeClock(now, **(clock_kwargs or {}))
        tab = FakeTab(clock, **(tab_kwargs or {}))
        timeline = sched.Timeline(run_at, clock, **kwargs)
        status = run(app.wait_until_release(
            tab, DAY, mode="p03", accept_terms=False, timeline=timeline,
            max_wait_seconds=sched.MAX_CUSTOM_WAIT_SECONDS))
        return status, tab, clock

    def test_refreshes_at_t_minus_10_and_exactly_at_start(self):
        status, tab, _ = self.wait(RELEASE - timedelta(seconds=120), RELEASE)
        self.assertEqual(status, "GRID_READY")
        self.assertEqual(tab.times("reload"), [RELEASE - timedelta(seconds=10), RELEASE])

    def test_custom_time_other_than_midnight_uses_the_same_logic(self):
        custom = datetime(2026, 11, 5, 9, 30, 15, tzinfo=TZ)
        status, tab, _ = self.wait(custom - timedelta(seconds=45), custom)
        self.assertEqual(status, "GRID_READY")
        self.assertEqual(tab.times("reload"), [custom - timedelta(seconds=10), custom])

    def test_started_two_hours_early_is_accepted_and_waits_until_the_time(self):
        status, tab, clock = self.wait(RELEASE - timedelta(hours=2), RELEASE)
        self.assertEqual(status, "GRID_READY")
        self.assertEqual(tab.times("reload")[-1], RELEASE)
        self.assertEqual(sum(clock.sleeps), 7200)

    def test_under_ten_seconds_skips_warmup_but_still_refreshes_on_time(self):
        status, tab, _ = self.wait(RELEASE - timedelta(seconds=4), RELEASE)
        self.assertEqual((status, tab.times("reload")), ("GRID_READY", [RELEASE]))

    def test_slightly_late_start_runs_immediately_without_waiting(self):
        status, tab, clock = self.wait(RELEASE + timedelta(seconds=12), RELEASE)
        self.assertEqual(status, "GRID_READY")
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(len(tab.times("reload")), 1)

    def test_start_time_missed_by_more_than_grace_never_refreshes_or_books(self):
        status, tab, _ = self.wait(RELEASE + timedelta(seconds=31), RELEASE)
        self.assertEqual((status, tab.log), ("RUN_AT_MISSED", []))

    def test_computer_sleep_during_standby_reports_missed_and_does_not_catch_up(self):
        status, tab, _ = self.wait(RELEASE - timedelta(minutes=5), RELEASE,
                                   clock_kwargs={"jumps": {100: 1800}})
        self.assertEqual(status, "RUN_AT_MISSED")
        self.assertEqual(tab.log, [])

    def test_wake_just_before_start_continues_and_fires_on_time(self):
        status, tab, _ = self.wait(RELEASE - timedelta(minutes=5), RELEASE,
                                   clock_kwargs={"jumps": {100: 150}})
        self.assertEqual(status, "GRID_READY")
        self.assertEqual(tab.times("reload")[-1], RELEASE)

    def test_cancel_during_standby_returns_cancelled_and_touches_nothing(self):
        state = {"n": 0}

        def cancelled():
            state["n"] += 1
            return state["n"] > 30
        status, tab, _ = self.wait(RELEASE - timedelta(minutes=5), RELEASE, cancelled=cancelled)
        self.assertEqual((status, tab.log), ("CANCELLED_BEFORE_START", []))

    def test_network_down_at_warmup_or_start_is_reported_not_swallowed(self):
        status, tab, _ = self.wait(RELEASE - timedelta(seconds=60), RELEASE,
                                   tab_kwargs={"reload_error": OSError("offline")})
        self.assertEqual(status, "PRE_REFRESH_BLOCKED_REFRESH_FAILED_OSError")
        status, _, _ = self.wait(RELEASE - timedelta(seconds=5), RELEASE,
                                 tab_kwargs={"reload_error": OSError("offline")})
        self.assertEqual(status, "RELEASE_REFRESH_BLOCKED_REFRESH_FAILED_OSError")

    def test_login_lost_is_reported_at_the_refresh(self):
        status, _, _ = self.wait(RELEASE - timedelta(seconds=60), RELEASE,
                                 tab_kwargs={"entry": "ENTRY_NOT_FOUND_OR_AMBIGUOUS"})
        self.assertEqual(status, "PRE_REFRESH_BLOCKED_ENTRY_NOT_FOUND_OR_AMBIGUOUS")

    def test_too_far_for_the_wait_window_is_refused(self):
        clock = FakeClock(RELEASE - timedelta(hours=30))
        timeline = sched.Timeline(RELEASE, clock)
        status = run(app.wait_until_release(FakeTab(clock), DAY, mode="p03", accept_terms=False,
                                            timeline=timeline, max_wait_seconds=86400))
        self.assertEqual(status, "RUN_AT_TOO_FAR")

    def test_legacy_default_path_keeps_its_fifteen_minute_window(self):
        from unittest.mock import patch
        with patch.object(app, "seconds_until_release", return_value=3600):
            status = run(app.wait_until_release(object(), DAY, mode="p03", accept_terms=False))
        self.assertEqual(status, "RELEASE_OUTSIDE_15_MINUTE_WINDOW")


def ntp_reply(offset):
    def seconds(t):
        whole = int(t) + sched.NTP_EPOCH_DELTA
        return whole, int((t - int(t)) * 2 ** 32)
    server_time = time.time() + offset
    fields = [0x1c000000] + [0] * 7 + [*seconds(server_time), *seconds(server_time)] + [0, 0]
    return struct.pack("!12I", *fields[:12])


class ClockSyncTests(unittest.TestCase):
    def test_sntp_offset_math_with_a_fake_socket(self):
        class Sock:
            def __init__(self, *a): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def settimeout(self, t): pass
            def sendto(self, data, addr): self.sent = (data, addr)
            def recvfrom(self, n): return ntp_reply(2.5), ("x", 123)
        self.assertAlmostEqual(sched.query_ntp_offset(sock_factory=Sock), 2.5, delta=0.3)

    def test_sntp_against_a_real_local_udp_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]

        def serve():
            data, addr = server.recvfrom(512)
            server.sendto(ntp_reply(-1.25), addr)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            offset = sched.query_ntp_offset("127.0.0.1", 2.0, port=port)
        finally:
            server.close()
        self.assertAlmostEqual(offset, -1.25, delta=0.3)

    def test_measure_never_blocks_scheduling(self):
        def broken():
            raise OSError("no network")
        offset, note = sched.measure_clock_offset(broken)
        self.assertIsNone(offset)
        self.assertIn("改用系統時間", note)
        self.assertIsNone(sched.measure_clock_offset(lambda: 9999)[0])
        self.assertAlmostEqual(sched.measure_clock_offset(lambda: 0.2)[0], 0.2)
        self.assertIn("已自動校正", sched.measure_clock_offset(lambda: 3.0)[1])


if __name__ == "__main__":
    unittest.main()
