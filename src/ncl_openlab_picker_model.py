# -*- coding: utf-8 -*-
"""Pure validation / CLI bridge for the NCL booking GUI (no UI side effects)."""
from datetime import date, datetime, timedelta, timezone

from ncl_openlab_rooms import get_registry

# Room choices and slots come from ncl_openlab_rooms.json, so a room added to
# the config appears in the GUI without any code change.
ROOM_CHOICES = {key: profile.ui_label for key, profile in get_registry().rooms.items()}
TAIPEI = timezone(timedelta(hours=8))


def available_slots(room):
    profile = get_registry().rooms.get(room)
    if profile is None:
        raise ValueError("不支援的空間")
    return profile.slots


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
        raise ValueError("請先勾選授權程式實際送出預約")
    if get_registry().room(room).submit_requires_ack:
        # Never acknowledge an unverified room on the user's behalf.
        raise ValueError("此空間尚未實機驗證，請改用命令列並明確加上 --ack-room-unverified")

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
    """Use console python.exe even when GUI launched via pythonw.exe."""
    from pathlib import Path, PureWindowsPath
    raw = str(executable)
    # Also works when checking a Windows path from a non-Windows test runner.
    interpreter = PureWindowsPath(raw) if "\\" in raw else Path(raw)
    if interpreter.name.lower() == "pythonw.exe":
        return str(interpreter.with_name("python.exe"))
    return str(interpreter)
