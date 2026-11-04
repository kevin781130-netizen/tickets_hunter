# -*- coding: utf-8 -*-
"""Pure validation / CLI bridge for the NCL booking GUI (no UI side effects)."""
from datetime import date, datetime, timedelta, timezone

from ncl_openlab_guard import VALID_SLOTS
from ncl_openlab_autobook import P03_SLOTS
from ncl_openlab_room_catalog import ROOM_CHOICES, room_status
from reservation_common import release_datetime as shared_release_datetime
TAIPEI = timezone(timedelta(hours=8))


def available_slots(room):
    if room == "music":
        return VALID_SLOTS
    if room == "p03":
        return P03_SLOTS
    # Catalog-only spaces are visible in the GUI, but we do not fabricate
    # room-specific time slots or allow any unverified booking actions.
    if room in ROOM_CHOICES:
        return ()
    raise ValueError("不支援的空間")


def release_datetime(day):
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("請選擇有效日期")
    return shared_release_datetime(day, days_before=7, tz=TAIPEI)


def build_booking_args(*, day, room, slots, immediate=False,
                       auto_submit=False, accept_terms=False, fallback_any_slot=False):
    """Return safe argv suffix; selecting two always means TWO reservations.

    Every slot must be known for its chosen room, with no duplicates. The
    backend remains responsible for only advancing after confirmed success.
    """
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("請先使用月曆選擇預約日期")
    if room not in ROOM_CHOICES:
        raise ValueError("請選擇正確空間")
    status = room_status(room)
    if status == "onsite_only":
        raise ValueError("此空間僅供現場借用，不提供線上自動預約")
    if status != "verified":
        raise ValueError("此空間的選房、時段與送出尚未實機驗證，不允許自動預約")
    selected = tuple(slots)
    if len(selected) not in (1, 2):
        raise ValueError("請選擇一個或兩個時段")
    if len(set(selected)) != len(selected):
        raise ValueError("時段不可重複")
    if any(s not in available_slots(room) for s in selected):
        raise ValueError("時段與房間不符")
    if not auto_submit:
        raise ValueError("請先勾選授權程式實際送出預約")

    args = ["--room", room, "--date", day.isoformat(),
            "--slots", ",".join(selected), "--auto-submit"]
    if len(selected) == 2:
        args.append("--reserve-two")
    if immediate:
        args.append("--now")
    if accept_terms:
        args.append("--accept-terms")
    if fallback_any_slot:
        args.append("--fallback-any-slot")
    return args



def console_python(executable):
    """Use console python.exe even when GUI launched via pythonw.exe."""
    from pathlib import Path, PureWindowsPath
    raw = str(executable)
    # Also works when checking a Windows path from a non-Windows test runner.
    interpreter = PureWindowsPath(raw) if "\\" in raw else Path(raw)
    if interpreter.name.lower() == "pythonw.exe":
        return str(interpreter.with_name("python.exe"))
    return str(interpreter)
