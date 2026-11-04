# -*- coding: utf-8 -*-
"""Pure validation / CLI bridge for the NCL booking GUI (no UI side effects)."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from ncl_openlab_rooms import get_registry
from ncl_openlab_schedule import (
    MAX_CUSTOM_WAIT_SECONDS, TAIPEI_TZ, check_run_at, parse_run_at, release_run_at,
)

# Room choices and slots come from ncl_openlab_rooms.json, so a room added to
# the config appears in the GUI without any code change.
ROOM_CHOICES = {key: profile.ui_label for key, profile in get_registry().rooms.items()}
TAIPEI = TAIPEI_TZ
ENGINE = Path(__file__).resolve().with_name("ncl_openlab_autobook.py")
RUN_AT_TEXT_FORMAT = "%Y-%m-%d %H:%M:%S"
SCHEDULE_ERRORS = {
    "RUN_AT_ALREADY_PASSED": "自訂啟動時間已經過了，請重設",
    "RUN_AT_TOO_FAR": "自訂啟動時間超過 24 小時，請改在較近的時間啟動",
    "RUN_AT_AFTER_TARGET_DAY": "啟動時間不可晚於預約日",
    "RUN_AT_INVALID": "啟動時間無法解讀",
}


def available_slots(room):
    profile = get_registry().rooms.get(room)
    if profile is None:
        raise ValueError("不支援的空間")
    return profile.slots


def room_requires_ack(room):
    profile = get_registry().rooms.get(room)
    return bool(profile and profile.submit_requires_ack)


def release_datetime(day):
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("請選擇有效日期")
    return release_run_at(day)


def default_run_at_text(day):
    """Default start: 7 days before the target day, 00:00:00 Taipei (editable)."""
    return release_datetime(day).strftime(RUN_AT_TEXT_FORMAT)


def parse_start_fields(date_text, time_text):
    """Combine the two entry boxes into an aware Taipei datetime."""
    text = f"{str(date_text).strip()} {str(time_text).strip()}"
    try:
        stamp = datetime.strptime(text, RUN_AT_TEXT_FORMAT)
    except ValueError:
        raise ValueError("啟動時間格式須為 YYYY-MM-DD 與 HH:MM:SS（24 小時制，台北時間）") from None
    return parse_run_at(stamp.isoformat())


def validate_start(day, run_at, now):
    """Chinese error text, or None when the custom start time is acceptable."""
    code = check_run_at(run_at, now, day, max_wait_seconds=MAX_CUSTOM_WAIT_SECONDS)
    return SCHEDULE_ERRORS[code] if code else None


def start_notes(day, run_at):
    """Non-blocking hints shown next to the schedule."""
    release = release_datetime(day)
    if run_at == release:
        return "預設：預約日前 7 日 00:00:00（預估放位時間，非官方保證）"
    if run_at < release:
        return "提醒：早於預估放位時間，日期可能尚未開放"
    return "已自訂啟動時間；若晚於放位時間，熱門時段可能已被預約"


def build_booking_args(*, day, room, slots, immediate=False, auto_submit=False,
                       accept_terms=False, run_at=None, ack_unverified=False,
                       sync_clock=False, machine_status=False, auth_check=False,
                       use_saved_login=False):
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
    if immediate and run_at is not None:
        raise ValueError("立即執行與自訂啟動時間不可同時使用")
    if run_at is not None and (not isinstance(run_at, datetime) or run_at.tzinfo is None):
        raise ValueError("啟動時間必須含時區")
    if use_saved_login and not auth_check:
        raise ValueError("自動填入登入資料需要同時啟用登入狀態檢查")
    if room_requires_ack(room) and not ack_unverified:
        # Never acknowledge an unverified room on the user's behalf.
        raise ValueError("此空間尚未實機驗證，請先勾選「我了解此設備尚未實機驗證」"
                         "（命令列為 --ack-room-unverified）")

    args = ["--room", room, "--date", day.isoformat(),
            "--slots", ",".join(selected), "--auto-submit"]
    if len(selected) == 2:
        args.append("--reserve-two")
    if immediate:
        args.append("--now")
    elif run_at is not None:
        args += ["--run-at", run_at.isoformat()]
    if accept_terms:
        args.append("--accept-terms")
    if room_requires_ack(room):
        args.append("--ack-room-unverified")
    if sync_clock:
        args.append("--sync-clock")
    if machine_status:
        args.append("--machine-status")
    if auth_check:
        args.append("--auth-check")
    if use_saved_login:
        args.append("--use-saved-login")
    return args


def engine_command(argv, executable=None):
    """Same interpreter and same engine on every platform."""
    return [console_python(executable or sys.executable), str(ENGINE), *argv]


def console_python(executable):
    """Use console python.exe even when GUI launched via pythonw.exe."""
    from pathlib import Path, PureWindowsPath
    raw = str(executable)
    # Also works when checking a Windows path from a non-Windows test runner.
    interpreter = PureWindowsPath(raw) if "\\" in raw else Path(raw)
    if interpreter.name.lower() == "pythonw.exe":
        return str(interpreter.with_name("python.exe"))
    return str(interpreter)


def summary_lines(*, day, room, slots, immediate, run_at):
    """Plain-text confirmation summary shared by the GUI and its confirmation box."""
    count = len(slots)
    when = ("立即執行（登入後馬上開始預約）" if immediate else
            f"{run_at:%Y-%m-%d %H:%M:%S}（台北時間）開始預約" if run_at else "尚未設定")
    return [f"房型／設備：{ROOM_CHOICES.get(room, room)}",
            f"預約日期：{day.isoformat()}",
            f"時段（{count} 筆，依序預約）：{' → '.join(slots) if slots else '尚未選擇'}",
            f"啟動：{when}"]
