# -*- coding: utf-8 -*-
"""Read-only diagnostics, outcome explanations and run reports for NCL booking.

Nothing here clicks, navigates or submits. The page script only counts and
inspects allowlisted class tokens; it never returns page text, form values,
cookies or account details.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ncl_openlab_rooms import get_registry

NCL_HOST = "spms.ncl.edu.tw"
TAIPEI_TZ = timezone(timedelta(hours=8))
REPORT_SCHEMA = 1
CLASS_ALLOWLIST = ("time-box", "time-box2", "book", "selected", "disabled",
                   "is-disabled", "reserving", "unavailable")
STAGES = ("DATE_GRID", "CHECKOUT", "RESULT", "OTHER")

DIAG_JS = r"""(() => {
  const task = __TASK__;
  const allow = __CLASS_ALLOWLIST__;
  const cleanText = (el) => String(el.innerText || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== "none" && style.visibility !== "hidden";
  };
  const disabled = (el) => el.classList.contains("disabled") ||
    el.classList.contains("is-disabled") || el.classList.contains("reserving") ||
    el.classList.contains("unavailable") || el.hasAttribute("disabled") ||
    el.getAttribute("aria-disabled") === "true";
  const from = (selector) => Array.from(document.querySelectorAll(selector)).filter(visible);
  const summarize = (items) => ({
    count: items.length,
    disabled: items.filter(disabled).length,
    selected: items.filter(el => el.classList.contains("selected")).length,
    book: items.filter(el => el.classList.contains("book")).length,
  });
  const roomMatches = (text) => task.profile.tileKind === "regex"
    ? new RegExp(task.profile.tileValue).test(text)
    : text.includes(task.profile.tileValue);
  const tokens = (el) => Array.from(el.classList).filter(c => allow.includes(c)).sort();
  if (location.hostname !== "spms.ncl.edu.tw") return {host: "OTHER", stage: "OTHER"};
  const display = String(document.body.innerText || "");
  const gobook = from("button#gobook.submit-circle-button").length;
  let stage = "OTHER";
  if (display.includes("預約成功") || display.includes("預約失敗")) stage = "RESULT";
  else if (gobook > 0) stage = "CHECKOUT";
  else if (document.querySelectorAll(".date-box").length > 0) stage = "DATE_GRID";
  const slotAll = from(task.profile.slotSelector);
  const slotTarget = slotAll.filter(el => el.getAttribute("data-param1") === task.slot);
  return {
    host: location.hostname, stage,
    date: summarize(from(".date-box").filter(el => cleanText(el).startsWith(task.shortDate))),
    room: summarize(from(".space-box1").filter(el => roomMatches(cleanText(el)))),
    slot: summarize(slotTarget),
    slots_visible: slotAll.length,
    slot_classes: slotTarget.length === 1 ? tokens(slotTarget[0]) : [],
    gobook_count: gobook,
  };
})()"""


def diagnose_script(day, slot, mode):
    """Fixed-target, side-effect-free page inspector for a given room profile."""
    profile = get_registry().room(mode)
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("invalid target day")
    if slot not in profile.slots:
        raise ValueError("invalid slot for requested room")
    task = {"shortDate": day.strftime("%m/%d"), "slot": slot,
            "profile": profile.task_profile()}
    return (DIAG_JS.replace("__TASK__", json.dumps(task, ensure_ascii=False))
            .replace("__CLASS_ALLOWLIST__", json.dumps(CLASS_ALLOWLIST)))


def _count_ok(group):
    return (isinstance(group, dict) and
            all(type(group.get(k)) is int and 0 <= group[k] <= 500
                for k in ("count", "disabled", "selected", "book")))


def validate_diag(raw):
    """Fail closed on any malformed or oversized page result."""
    if not isinstance(raw, dict) or raw.get("host") != NCL_HOST:
        return None
    if raw.get("stage") not in STAGES:
        return None
    if not all(_count_ok(raw.get(k)) for k in ("date", "room", "slot")):
        return None
    classes = raw.get("slot_classes")
    if (not isinstance(classes, list) or
            any(c not in CLASS_ALLOWLIST for c in classes)):
        return None
    for key in ("slots_visible", "gobook_count"):
        if type(raw.get(key)) is not int or not 0 <= raw[key] <= 500:
            return None
    return raw


def diagnose(raw, mode):
    """Turn a validated page snapshot into findings. Never claims availability."""
    profile = get_registry().room(mode)
    data = validate_diag(raw)
    if data is None:
        return {"stage": "UNKNOWN", "findings": ["DIAG_RESULT_INVALID"],
                "ready_to_select": False, "availability_verified": False}
    findings = []
    if data["stage"] != "DATE_GRID":
        findings.append("NOT_ON_DATE_GRID_" + data["stage"])
    else:
        for label, key in (("DATE", "date"), ("ROOM", "room")):
            group = data[key]
            if group["count"] == 0:
                findings.append(label + "_NOT_FOUND")
            elif group["count"] > 1:
                findings.append(label + "_NOT_UNIQUE")
            elif group["disabled"]:
                findings.append(label + "_DISABLED")
        slot = data["slot"]
        if slot["count"] == 0:
            findings.append("SLOT_NOT_RENDERED_OR_NOT_IN_VIEW")
        elif slot["count"] > 1:
            findings.append("SLOT_NOT_UNIQUE")
        else:
            if slot["disabled"]:
                findings.append("SLOT_DISABLED_UI_HINT")
            elif (profile.flow.slot_requires_book_class and slot["book"] == 0):
                findings.append("SLOT_MISSING_REQUIRED_BOOK_CLASS")
    ready = data["stage"] == "DATE_GRID" and not findings
    return {"stage": data["stage"],
            "findings": findings or ["TARGET_VISIBLE_UI_ONLY"],
            "ready_to_select": ready,
            # A visible, enabled tile is never proof of back-end availability.
            "availability_verified": False,
            "slot_classes": list(data["slot_classes"])}


OUTCOME_HINTS = {
    "SUCCESS_PAGE_MATCHED": ("SUCCESS_CONFIRMED", "官方成功頁已核對日期、房型與時段。"),
    "FAILURE_SHOWN": ("FAILED", "網站顯示預約失敗；不要自動補送，請到官網核對。"),
    "SUBMITTED_SUCCESS_UNVERIFIED": (
        "UNKNOWN_DO_NOT_RETRY", "已送出但未見成功頁；請至官網「我的紀錄」核對，勿重送。"),
    "PREVIEW_STOPPED_BEFORE_SUBMIT": ("STOPPED_BY_DESIGN", "未授權送出，已停在最後確認前。"),
    "TWO_BOOKINGS_CONFIRMED": ("SUCCESS_CONFIRMED", "兩筆預約都已在官方成功頁核對。"),
    "DRY_RUN_COMPLETE": ("DRY_RUN", "僅唯讀診斷，沒有點選預約相關控制項。"),
    "CANCELLED_BEFORE_START": ("CANCELLED", "排程在開始預約前已取消，沒有送出任何預約。"),
    "AUTH_NO_RESPONSE": ("BLOCKED", "等不到你完成登入或驗證碼，已停止，沒有預約。"),
    "AUTH_FAILED": ("BLOCKED", "登入連續失敗，已停止以避免帳號被鎖；請確認帳密與驗證碼後重新啟動。"),
    "AUTH_NOT_COMPLETED_BEFORE_START": ("BLOCKED", "到預定時間前仍未完成登入／驗證，已停止，沒有在未知登入狀態下預約。"),
    "SESSION_EXPIRED_NOT_RECOVERED": ("BLOCKED", "登入逾時且到點前沒有完成重新驗證，已放棄預約，沒有送出。"),
    "BROWSER_UNREACHABLE": ("BLOCKED", "瀏覽器分頁沒有回應（可能被關閉），已停止，沒有預約。"),
    "RUN_AT_MISSED": ("BLOCKED", "已錯過預定時間（電腦睡眠或程式停滯）；不會補送，請重新設定。"),
    "RUN_AT_ALREADY_PASSED": ("BLOCKED", "預定時間已過，沒有執行。"),
    "RUN_AT_TOO_FAR": ("BLOCKED", "預定時間離現在太遠，沒有等待。"),
    "RUN_AT_AFTER_TARGET_DAY": ("BLOCKED", "預定時間晚於預約日，沒有執行。"),
    "PREFLIGHT_TARGET_INVALID": ("BLOCKED", "預約目標（日期、房型或時段）檢查未通過，沒有執行。"),
    "INVALID_TWO_BOOKING_CONFIGURATION": ("BLOCKED", "兩筆預約設定不合法，沒有執行。"),
    "INVALID_DRY_RUN_WITH_AUTO_SUBMIT": ("BLOCKED", "診斷模式不可授權送出，沒有執行。"),
    "NO_BOOKABLE_UI_SLOT": ("RETRYABLE_BEFORE_SUBMIT", "指定時段目前沒有可點選的介面狀態。"),
    "BLOCKED_DATE_NOT_UNIQUE": ("RETRYABLE_BEFORE_SUBMIT", "日期方塊不存在或不唯一，可能尚未開放。"),
    "BLOCKED_DATE_DISABLED": ("RETRYABLE_BEFORE_SUBMIT", "日期被禁用，可能尚未開放。"),
    "BLOCKED_ROOM_NOT_UNIQUE": ("RETRYABLE_BEFORE_SUBMIT", "房型方塊不存在或不唯一。"),
    "BLOCKED_ROOM_DISABLED": ("BLOCKED", "房型方塊被禁用。"),
    "BLOCKED_CHECKOUT_NOT_READY": ("BLOCKED", "最後確認頁未在時限內載入完成。"),
    "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY": (
        "UNKNOWN_DO_NOT_RETRY", "送出結果不明；請至官網核對，勿重送。"),
    "RELEASE_OUTSIDE_15_MINUTE_WINDOW": ("BLOCKED", "不在放位前 15 分鐘窗口內；請用 --now 或調整啟動時間。"),
}
_PREFIX_HINTS = (
    ("PRE_REFRESH_BLOCKED_SESSION_EXPIRED", ("BLOCKED", "預刷新時網站要求重新登入（登入逾時），未預約。")),
    ("RELEASE_REFRESH_BLOCKED_SESSION_EXPIRED", ("BLOCKED", "準點刷新時網站要求重新登入（登入逾時），未預約。")),
    ("RETRY_ENTRY_BLOCKED_SESSION_EXPIRED", ("BLOCKED", "重試期間網站要求重新登入（登入逾時），未再送出。")),
    ("REENTRY_BLOCKED_", ("BLOCKED", "重新登入後無法回到日期頁，已停止。")),
    ("SESSION_CHECK_BLOCKED_", ("BLOCKED", "待命期間的登入檢查無法回到日期頁，已停止。")),
    ("DATE_GRID_NOT_READY_", ("BLOCKED", "無法進入日期頁（入口或條款狀態不明），已停止。")),
    ("RELEASE_WINDOW_EXHAUSTED_", ("WINDOW_EXHAUSTED", "重試時限用完，仍未出現可預約介面。")),
    ("RETRY_ENTRY_BLOCKED_", ("BLOCKED", "重新整理後無法回到日期頁（入口、條款或登入問題）。")),
    ("PRE_REFRESH_BLOCKED_", ("BLOCKED", "預刷新後無法回到日期頁（可能登入失效或網路中斷）；未送出。")),
    ("RELEASE_REFRESH_BLOCKED_REFRESH_FAILED_", ("BLOCKED", "準點刷新失敗（網路中斷或分頁異常）；未送出，請檢查網路與登入。")),
    ("RELEASE_REFRESH_BLOCKED_", ("BLOCKED", "準點刷新後無法回到日期頁（可能登入失效或入口改版）；未送出。")),
    ("FIRST_UNVERIFIED_SECOND_NOT_ATTEMPTED_", ("UNKNOWN_DO_NOT_RETRY", "第一筆未確認，第二筆未執行。")),
    ("SECOND_NOT_CONFIRMED_", ("UNKNOWN_DO_NOT_RETRY", "第二筆未確認成功；請至官網核對。")),
    ("SECOND_ENTRY_BLOCKED_", ("BLOCKED", "第二筆入口無法回到日期頁。")),
    ("EXCEPTION_", ("ERROR", "程式例外；請先到官網核對是否已有預約。")),
    ("BLOCKED_", ("BLOCKED", "安全檢查擋下，未送出；詳見 trace。")),
)


def explain_outcome(code):
    """Category and Chinese hint for a terminal outcome code."""
    if code in OUTCOME_HINTS:
        category, hint = OUTCOME_HINTS[code]
    else:
        category, hint = "UNCLASSIFIED", "未列入診斷表的結果代碼；請看 trace。"
        for prefix, value in _PREFIX_HINTS:
            if str(code).startswith(prefix):
                category, hint = value
                break
    return {"code": code, "category": category, "hint": hint}


_CODE_RE = re.compile(r"^[A-Za-z0-9_ :.\-]{1,80}$")


def sanitize_trace(trace):
    """Keep only short code-like tokens; anything else is replaced."""
    clean = []
    for entry in trace or ():
        if (isinstance(entry, (tuple, list)) and len(entry) == 2 and
                all(isinstance(x, str) and _CODE_RE.match(x) for x in entry)):
            clean.append({"step": entry[0], "code": entry[1]})
        else:
            clean.append({"step": "REDACTED", "code": "REDACTED"})
    return clean


def build_report(*, day, mode, priorities, outcome, trace, flags,
                 diagnosis=None, screenshot=None, now=None, schedule=None):
    profile = get_registry().room(mode)
    stamp = (now or datetime.now(TAIPEI_TZ)).astimezone(TAIPEI_TZ)
    return {
        "schema": REPORT_SCHEMA,
        "created_taipei": stamp.isoformat(timespec="seconds"),
        "target": {"date": day.isoformat(), "room": mode, "flow": profile.flow.name,
                   "slots": list(priorities), "live_evidence": profile.live},
        "flags": {k: bool(v) for k, v in sorted(flags.items())},
        "outcome": explain_outcome(outcome),
        "trace": sanitize_trace(trace),
        "schedule": schedule,
        "diagnosis": diagnosis,
        "screenshot": screenshot,
        "privacy": "no page text, cookies, credentials or form values recorded",
    }


def write_report(report_dir, report, stem=None):
    """Write the JSON report; returns its path. Overwrites nothing."""
    folder = Path(report_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = stem or "ncl_run_" + datetime.now(TAIPEI_TZ).strftime("%Y%m%d_%H%M%S")
    path = folder / (name + ".json")
    counter = 1
    while path.exists():
        counter += 1
        path = folder / f"{name}_{counter}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def screenshot_path(report_dir, stem):
    folder = Path(report_dir)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (stem + ".png")


async def capture_screenshot(tab, report_dir, stem):
    """Best effort screenshot. Pages may show account details: keep local only."""
    path = screenshot_path(report_dir, stem)
    try:
        await tab.save_screenshot(str(path))
    except Exception:
        return None
    return path.name
