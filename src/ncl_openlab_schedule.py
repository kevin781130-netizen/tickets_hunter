# -*- coding: utf-8 -*-
"""Scheduling core for the NCL booking engine: one clock, one timeline.

Everything is Asia/Taipei (UTC+8, no DST). The default start time is still the
estimated release moment (target day minus 7 days, 00:00:00), but any aware or
naive ("Taipei local") timestamp may be chosen. The same Timeline drives the
T-10 warm-up and the T=0 refresh whatever the start time is.

No network access except the optional, explicit SNTP query.
"""
import asyncio
import socket
import struct
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

TAIPEI_TZ = timezone(timedelta(hours=8))
LATE_GRACE_SECONDS = 30.0   # starting this late is still acceptable
JUMP_THRESHOLD = 5.0        # wall-clock vs. expected sleep: laptop slept / clock set
CHUNK_SECONDS = 1.0
MAX_CUSTOM_WAIT_SECONDS = 24 * 3600
MAX_CLOCK_OFFSET = 600.0    # refuse to apply an absurd correction
NTP_EPOCH_DELTA = 2208988800


class ScheduleMissed(Exception):
    """The start time passed while the machine slept or stalled."""


class ScheduleCancelled(Exception):
    """The user cancelled while the schedule was still waiting."""


def release_run_at(day):
    """Default start: seven days before the target day, 00:00:00 Taipei."""
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("invalid target day")
    return datetime.combine(day - timedelta(days=7), dtime.min, tzinfo=TAIPEI_TZ)


def parse_run_at(text):
    """Parse a start time into an aware Taipei datetime. Date-only is rejected.

    Accepts ISO 8601 (with offset or 'Z') and 'YYYY-MM-DD HH:MM[:SS]'. A value
    without an offset is Taipei local time. Fractional seconds are dropped.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("start time is empty")
    raw = text.strip()
    if "T" not in raw and " " not in raw:
        raise ValueError("start time needs a time of day, e.g. 2026-11-05T00:00:00+08:00")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00") if raw.endswith("Z") else raw)
    except ValueError:
        raise ValueError(f"cannot read start time: {raw[:40]!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ).replace(microsecond=0)


def check_run_at(run_at, now, day, *, max_wait_seconds, grace=0.0):
    """Return None when acceptable, otherwise a stable error code."""
    if not isinstance(run_at, datetime) or run_at.tzinfo is None:
        return "RUN_AT_INVALID"
    if run_at.astimezone(TAIPEI_TZ).date() > day:
        return "RUN_AT_AFTER_TARGET_DAY"
    remaining = (run_at - now).total_seconds()
    if remaining < -grace:
        return "RUN_AT_ALREADY_PASSED"
    if remaining > max_wait_seconds:
        return "RUN_AT_TOO_FAR"
    return None


def format_countdown(seconds):
    total = max(0, int(seconds))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    clock = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{days} 天 {clock}" if days else clock


class SystemClock:
    """Wall clock in Taipei time with an optional measured/manual correction."""

    def __init__(self, offset_seconds=0.0):
        if abs(offset_seconds) > MAX_CLOCK_OFFSET:
            raise ValueError("clock offset is implausibly large")
        self.offset_seconds = float(offset_seconds)

    def now(self):
        return datetime.now(TAIPEI_TZ) + timedelta(seconds=self.offset_seconds)

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class Timeline:
    """Wait for ``run_at`` in short steps so sleep, clock jumps and cancel are seen.

    ``remaining()`` / ``sleep()`` are the only interface the wait logic needs, so
    the legacy release wait (plain asyncio.sleep) and this one share one algorithm.
    """

    def __init__(self, run_at, clock=None, *, grace=LATE_GRACE_SECONDS,
                 cancelled=None, on_event=None):
        self.run_at = run_at
        self.clock = clock or SystemClock()
        self.grace = grace
        self.cancelled = cancelled or (lambda: False)
        self.on_event = on_event or (lambda kind, detail: None)
        self.events = []

    def remaining(self):
        return (self.run_at - self.clock.now()).total_seconds()

    def _event(self, kind, detail):
        self.events.append((kind, detail))
        self.on_event(kind, detail)

    async def sleep(self, seconds):
        target = self.clock.now() + timedelta(seconds=seconds)
        while True:
            left = (target - self.clock.now()).total_seconds()
            if left <= 0:
                break
            if self.cancelled():
                raise ScheduleCancelled()
            step = min(CHUNK_SECONDS, left)
            before = self.clock.now()
            await self.clock.sleep(step)
            drift = (self.clock.now() - before).total_seconds() - step
            if abs(drift) > JUMP_THRESHOLD:
                self._event("CLOCK_JUMP", round(drift, 1))
            if self.remaining() < -self.grace:
                raise ScheduleMissed()
        if self.cancelled():
            raise ScheduleCancelled()
        if self.remaining() < -self.grace:
            raise ScheduleMissed()


def query_ntp_offset(server="pool.ntp.org", timeout=2.0, *, port=123, sock_factory=socket.socket):
    """SNTP offset in seconds (server minus local). Raises OSError on failure."""
    packet = b"\x1b" + 47 * b"\0"
    with sock_factory(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        t1 = time.time()
        sock.sendto(packet, (server, port))
        data, _ = sock.recvfrom(512)
        t4 = time.time()
    if len(data) < 48:
        raise OSError("short NTP reply")
    fields = struct.unpack("!12I", data[:48])
    to_unix = lambda sec, frac: sec - NTP_EPOCH_DELTA + frac / 2 ** 32  # noqa: E731
    t2, t3 = to_unix(fields[8], fields[9]), to_unix(fields[10], fields[11])
    return ((t2 - t1) + (t3 - t4)) / 2.0


def measure_clock_offset(query=query_ntp_offset):
    """(offset or None, message). A failure never blocks scheduling."""
    try:
        offset = float(query())
    except Exception as exc:
        return None, f"校時失敗（{type(exc).__name__}），改用系統時間"
    if abs(offset) > MAX_CLOCK_OFFSET:
        return None, f"校時結果異常（{offset:+.1f} 秒），已忽略"
    note = "系統時間與網路時間誤差在 1 秒內" if abs(offset) < 1 else \
        f"系統時間與網路時間相差 {offset:+.1f} 秒，已自動校正排程"
    return offset, note
