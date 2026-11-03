# -*- coding: utf-8 -*-
"""Pure validation / CLI bridge for the NCL booking GUI (no UI side effects)."""
from datetime import date, datetime, timedelta, timezone

from ncl_openlab_guard import VALID_SLOTS
from ncl_openlab_autobook import P03_SLOTS

ROOM_CHOICES = {"music": "音樂創作室（3 小時）", "p03": "P03 個人直播室（1 小時）"}
TAIPEI = timezone(timedelta(hours=8))


def available_slots(room):
    if room == "music":
        return VALID_SLOTS
    if room == "p03":
        return P03_SLOTS
    raise ValueError("不支援的空間")


def release_datetime(day):
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("請選擇有效日期")
    return datetime.combine(day - timedelta(days=7),
                            datetime.min.time(), tzinfo=TAIPEI)


def build_booking_args(*, day, room, slots, immediate=False,
                       auto_submit=False, accept_terms=False):
    """Return safe argv suffix; selecting two always means TWO reservations.

    Every slot must be known for its chosen room, with no duplicates. The
    backend remains responsible for only advancing after confirmed success.
    """
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("請先使用月曆選擇預約日期")
    if room not in ROOM_CHOICES:
        raise ValueError("請選擇正確空間")
    selected = tuple(slots)
    if len(selected) not in (1, 2):
        raise ValueError("請選擇一個或兩個時段")
    if len(set(selected)) != len(selected):
        raise ValueError("時段不可重複")
    if any(s not in available_slots(room) for s in selected):
        raise ValueError("時段與房間不符")
    if not auto_submit:
        raise ValueError("請先確認同意程式實際送出預約")

    args = ["--room", room, "--date", day.isoformat(),
            "--slots", ",".join(selected), "--auto-submit"]
    if len(selected) == 2:
        args.append("--reserve-two")
    if immediate:
        args.append("--now")
    if accept_terms:
        args.append("--accept-terms")
    return args



def console_python(executable):
    """pythonw.exe has no interactive stdin; spawn console python.exe instead."""
    from pathlib import Path
    interpreter = Path(executable)
    if interpreter.name.lower() == "pythonw.exe":
        return str(interpreter.with_name("python.exe"))
    return str(interpreter)
