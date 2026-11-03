#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot, opt-in NCL music-room or P03 booking through the visible browser UI.

Manual login required. One target date, one room, at most one final submit.
No API replay, CAPTCHA solving, rapid page refresh or continuous polling.
"""
import argparse
import asyncio
import json
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit

from ncl_openlab_guard import NCL_HOST, ROOM, VALID_SLOTS
from ncl_openlab_probe import NCL_URL, TAIPEI_TZ
from ncl_openlab_slots import parse_slot_priority

# Fixed, exact labels and site selectors. Never click unknown elements.
PHASES = ("date", "room", "slot", "next", "submit", "success")
P03_SLOTS = tuple(f"{hour:02d}:00-{hour + 1:02d}:00" for hour in range(9, 20))
ROOM_MODES = ("music", "p03")
ACTION_JS = r"""(() => {
  const task = __TASK__;
  const cleanText = (el) => String(el.innerText || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== "none" && style.visibility !== "hidden";
  };
  const disabled = (el) => el.classList.contains("disabled") ||
    el.classList.contains("is-disabled") ||
    el.classList.contains("reserving") ||
    el.classList.contains("unavailable") ||
    el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true";
  const exactOne = (items) => items.length === 1 ? items[0] : null;
  const from = (selector) => Array.from(document.querySelectorAll(selector))
    .filter(visible);
  const dateTile = () => exactOne(from(".date-box")
    .filter(el => cleanText(el).startsWith(task.shortDate)));
  const roomTile = () => exactOne(from(".space-box1")
    .filter(el => task.mode === "p03"
      ? /^P03(?:\s|$)/.test(cleanText(el))
      : cleanText(el).includes(task.room)));
  const slotTile = () => exactOne(from(task.mode === "p03"
    ? ".time-box[data-param1]" : ".time-box2[data-param1]")
    .filter(el => el.getAttribute("data-param1") === task.slot));
  // P03 marks the clicked/selected hour with 'book' (observed live HTML).
  // Music-room tiles use 'selected'; keep these two state contracts separate.
  const chosen = (el, kind) => el && (el.classList.contains("selected") ||
    (task.mode === "p03" && kind === "slot" && el.classList.contains("book")));
  const result = (code) => ({code}); // No page content, identifiers or account data.
  if (location.hostname !== "spms.ncl.edu.tw") return result("WRONG_HOST");
  // Never switch between distinct pages without re-verifying the intended stage.
  if (task.phase === "date") {
    const tile = dateTile();
    if (!tile) return result("DATE_NOT_UNIQUE");
    if (disabled(tile)) return result("DATE_DISABLED");
    if (chosen(tile)) return result("ALREADY_SELECTED");
    tile.click(); return result("CLICKED");
  }
  if (task.phase === "room") {
    if (!chosen(dateTile())) return result("DATE_NOT_SELECTED");
    const tile = roomTile();
    if (!tile) return result("ROOM_NOT_UNIQUE");
    if (disabled(tile)) return result("ROOM_DISABLED");
    if (chosen(tile)) return result("ALREADY_SELECTED");
    tile.click(); return result("CLICKED");
  }
  if (task.phase === "slot") {
    if (!chosen(dateTile()) || !chosen(roomTile())) return result("CONTEXT_NOT_SELECTED");
    const tile = slotTile();
    if (!tile) return result("SLOT_NOT_UNIQUE");
    // Positive UI hint is mandatory, but is NEVER back-end availability proof.
    if (disabled(tile)) return result("SLOT_DISABLED");
    // A P03 brown .time-box can be chosen before it gains 'book'.
    // For music-room time-box2 keep the positive 'book' requirement.
    if (task.mode !== "p03" && !tile.classList.contains("book"))
      return result("SLOT_NOT_BOOK_CLASS");
    if (chosen(tile, "slot")) return result("ALREADY_SELECTED");
    tile.click(); return result("CLICKED");
  }
  const cta = (word) => {
    // NCL's round booking control may render with spacing: 預 約.
    // Compare fixed allowlisted CTA labels only, ignoring whitespace, never partial words.
    const exactLabel = (value) => String(value || "").replace(/\s+/g, "") === word;
    const matches = from("button, a, div, span, [role='button'], input[type='button'], input[type='submit']")
      .filter(el => exactLabel(el.innerText) ||
        (el.matches("input") && exactLabel(el.value)));
    // Prefer the innermost exact label, then its nearest actionable ancestor.
    const leaf = exactOne(matches.filter(el => !matches.some(child =>
      child !== el && el.contains(child))));
    if (!leaf) return null;
    const clickable = leaf.closest("button, a, [role='button'], input[type='button'], input[type='submit']");
    const candidate = clickable && visible(clickable) ? clickable : leaf;
    return disabled(candidate) || disabled(leaf) ? null : candidate;
  };
  if (task.phase === "next") {
    if (!chosen(dateTile()) || !chosen(roomTile()) ||
        !chosen(slotTile(), "slot")) return result("TARGET_NOT_SELECTED");
    const button = cta("下一步");
    if (!button || disabled(button)) return result("NEXT_NOT_ACTIONABLE");
    button.click(); return result("CLICKED");
  }
  // Final confirmation page may no longer have .date-box and .space-box1.
  // Compare all three target facts in the rendered visible page, not form values.
  const matchingRoomSummary = (display) => task.mode === "p03"
    ? display.replace(/\s+/g, "").includes("個人直播室") && /\bP03\b/.test(display)
    : display.replace(/\s+/g, "").includes(task.room);
  const summary = () => {
    const display = String(document.body.innerText || "");
    return display.includes(task.fullDate) &&
      matchingRoomSummary(display) && display.includes(task.slot);
  };
  if (task.phase === "submit") {
    if (window.__nclOneShotSubmit === true) return result("ALREADY_SUBMITTED");
    if (!summary()) return result("SUMMARY_MISMATCH");
    // Exact markup from the live confirmation screen. Never reuse dynamic IDs.
    const buttons = from("button#gobook.submit-circle-button");
    const button = exactOne(buttons);
    if (!button || disabled(button) ||
        cleanText(button).replace(/\s+/g, "") !== "預約")
      return result("SUBMIT_NOT_ACTIONABLE");
    // These are the public target date and slot, NOT the dynamic session IDs.
    if (button.getAttribute("data-param2") !== task.isoDate ||
        button.getAttribute("data-param5") !== task.slot)
      return result("SUBMIT_TARGET_MISMATCH");
    const bounds = button.getBoundingClientRect();
    const x = bounds.left + bounds.width / 2;
    const y = bounds.top + bounds.height / 2;
    const hit = document.elementFromPoint(x, y);
    if (!Number.isFinite(x) || !Number.isFinite(y) ||
        !hit || (hit !== button && !button.contains(hit)))
      return result("SUBMIT_BUTTON_OCCLUDED");
    window.__nclOneShotSubmit = true;
    return {code: "READY_FOR_POINTER_CLICK", x, y};
  }
  if (task.phase === "success") {
    const display = String(document.body.innerText || "");
    if (display.includes("預約成功") &&
        display.includes(task.fullDate) &&
        display.includes(task.slot) &&
        matchingRoomSummary(display)) return result("SUCCESS_PAGE_MATCHED");
    if (display.includes("預約失敗")) return result("FAILURE_SHOWN");
    return result("SUCCESS_NOT_VERIFIED");
  }
  return result("UNKNOWN_PHASE");
})()"""


def action_script(phase, day, slot, mode="music"):
    if phase not in PHASES or mode not in ROOM_MODES:
        raise ValueError("invalid phase or room mode")
    allowed = VALID_SLOTS if mode == "music" else P03_SLOTS
    if (not isinstance(day, date) or isinstance(day, datetime)
            or slot not in allowed):
        raise ValueError("invalid slot for requested room")
    room = ROOM if mode == "music" else "個人直播室"
    data = {"phase": phase, "shortDate": day.strftime("%m/%d"),
            "fullDate": day.strftime("%Y/%m/%d"),
            "isoDate": day.isoformat(), "room": room,
            "slot": slot, "mode": mode}
    return ACTION_JS.replace("__TASK__", json.dumps(data, ensure_ascii=False))


def release_time(day):
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("invalid target day")
    # Seven days before target. 00:00 is a user-observed timing assumption,
    # not a confirmed NCL time-of-day guarantee.
    return datetime.combine(day - timedelta(days=7), time.min, tzinfo=TAIPEI_TZ)


def seconds_until_release(day, now=None):
    t = now or datetime.now(TAIPEI_TZ)
    if t.tzinfo is None:
        raise ValueError("now must have timezone")
    return (release_time(day) - t.astimezone(TAIPEI_TZ)).total_seconds()


# One-shot lobby navigation from actual NCL entry markup. Consent is opt-in.
ENTRY_JS = r"""(() => {
  const action = __ALLOW_AGREE__;
  const visible = (el) => {
    const b = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return b.width > 0 && b.height > 0 && style.display !== "none" &&
      style.visibility !== "hidden";
  };
  if (location.hostname !== "spms.ncl.edu.tw") return "WRONG_HOST";
  if (document.querySelectorAll(".date-box").length > 0) return "GRID_READY";
  const agrees = Array.from(document.querySelectorAll("button#agree-btn.button.agree"))
    .filter(visible);
  if (agrees.length === 1) {
    if (!action) return "AGREEMENT_REQUIRED";
    if (String(agrees[0].innerText || "").replace(/\\s+/g, "") !== "同意Agree")
      return "AGREEMENT_LABEL_CHANGED";
    agrees[0].click();
    return "AGREEMENT_CLICKED";
  }
  const choices = Array.from(document.querySelectorAll(".art-image.multimedia"))
    .filter(visible);
  if (choices.length !== 1) return "ENTRY_NOT_FOUND_OR_AMBIGUOUS";
  choices[0].click();
  return "MULTIMEDIA_OPENED";
})()"""


async def ensure_date_grid(tab, *, accept_terms=False):
    """At most five local DOM checks; never bypass or infer consent."""
    if not await at_official_host(tab):
        return "WRONG_HOST"
    code = "ENTRY_NOT_FOUND_OR_AMBIGUOUS"
    for _ in range(5):
        code = await tab.evaluate(
            ENTRY_JS.replace("__ALLOW_AGREE__", "true" if accept_terms else "false"))
        if code == "GRID_READY":
            return code
        if code not in ("MULTIMEDIA_OPENED", "AGREEMENT_CLICKED"):
            return code
        await asyncio.sleep(0.3)
    return code


async def at_official_host(tab):
    url = await tab.evaluate("location.href")
    return urlsplit(url).hostname == NCL_HOST


async def read_action(tab, phase, day, slot, mode="music"):
    if not await at_official_host(tab):
        raise RuntimeError("NOT_OFFICIAL_NCL_HOST")
    response = await tab.evaluate(action_script(phase, day, slot, mode))
    if not isinstance(response, dict) or response.get("code") not in {
        "WRONG_HOST", "DATE_NOT_UNIQUE", "DATE_DISABLED", "ALREADY_SELECTED",
        "CLICKED", "DATE_NOT_SELECTED", "ROOM_NOT_UNIQUE", "ROOM_DISABLED",
        "CONTEXT_NOT_SELECTED", "SLOT_NOT_UNIQUE", "SLOT_DISABLED",
        "SLOT_NOT_BOOK_CLASS", "TARGET_NOT_SELECTED",
        "NEXT_NOT_ACTIONABLE", "ALREADY_SUBMITTED", "SUMMARY_MISMATCH",
        "SUBMIT_NOT_ACTIONABLE", "CLICKED_ONCE", "SUCCESS_PAGE_MATCHED",
        "FAILURE_SHOWN", "SUCCESS_NOT_VERIFIED", "UNKNOWN_PHASE"
    }:
        raise RuntimeError("INVALID_ACTION_RESULT")
    return response["code"]


async def submit_once_with_pointer(tab, day, slot, mode="music", attempts=8):
    """Validate the exact #gobook target, then dispatch ONE native pointer click.

    If the click times out or its outcome is uncertain, never submit again.
    Merely dispatching the click does not prove a completed reservation.
    """
    if not await at_official_host(tab):
        return "NOT_OFFICIAL_NCL_HOST"
    for i in range(attempts):
        raw = await tab.evaluate(action_script("submit", day, slot, mode))
        if not isinstance(raw, dict) or not isinstance(raw.get("code"), str):
            return "INVALID_SUBMIT_RESULT"
        code = raw["code"]
        if code == "READY_FOR_POINTER_CLICK":
            x, y = raw.get("x"), raw.get("y")
            if (isinstance(x, bool) or isinstance(y, bool) or
                    not isinstance(x, (int, float)) or
                    not isinstance(y, (int, float)) or
                    not (0 < x < 10000 and 0 < y < 10000)):
                return "INVALID_SUBMIT_COORDINATES"
            try:
                await tab.mouse_click(float(x), float(y))
            except Exception:
                # A failed mouse call may still have reached the site.
                return "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY"
            return "CLICKED_ONCE"
        if code in ("SUBMIT_NOT_ACTIONABLE", "SUMMARY_MISMATCH") and i < attempts - 1:
            await asyncio.sleep(0.2)
            continue
        return code
    return "SUBMIT_NOT_ACTIONABLE"


async def attempt_stage(tab, phase, day, slot, attempts=6, mode="music"):
    """Only reread the local DOM; no extra HTTP requests or page refreshes."""
    transient = {
        "date": {"DATE_NOT_UNIQUE"},
        "room": {"ROOM_NOT_UNIQUE"},
        "slot": {"SLOT_NOT_UNIQUE"},
        "next": {"NEXT_NOT_ACTIONABLE", "TARGET_NOT_SELECTED"},
        "submit": {"SUBMIT_NOT_ACTIONABLE", "SUMMARY_MISMATCH"},
    }.get(phase, set())
    for i in range(attempts):
        # Keep the original music-mode call contract for existing tests.
        code = (await read_action(tab, phase, day, slot) if mode == "music"
                else await read_action(tab, phase, day, slot, mode))
        if code not in transient or i == attempts - 1:
            return code
        await asyncio.sleep(0.2)
    return code


async def autobook(day, priorities, *, auto_submit, now_mode=False,
                   mode="music", accept_terms=False):
    import zendriver as uc

    browser = await uc.start(headless=False)
    try:
        tab = await browser.get(NCL_URL)
        print("在此瀏覽器手動登入並開啟多媒體創意實驗中心的日期選擇畫面。")
        await asyncio.to_thread(input, "登入及進入頁面後按 Enter 啟動單次自動預約：")
        status = await ensure_date_grid(tab, accept_terms=accept_terms)
        if status == "AGREEMENT_REQUIRED":
            print("請親自閱讀並點選「同意 Agree」，返回日期頁後再按 Enter。")
            await asyncio.to_thread(input, "已同意並進入日期頁後按 Enter：")
            status = await ensure_date_grid(tab, accept_terms=False)
        if status != "GRID_READY":
            raise RuntimeError("DATE_GRID_NOT_READY_" + str(status))
        if not now_mode:
            remaining = seconds_until_release(day)
            if not 0 <= remaining <= 900:
                raise RuntimeError("RELEASE_OUTSIDE_15_MINUTE_WINDOW")
            print("等待國圖預約開放時間（台北時間），到點只刷新一次。")
            if remaining:
                await asyncio.sleep(remaining)
            await tab.reload(ignore_cache=False)
            await tab.wait_for_ready_state(until="interactive", timeout=10)
            status = await ensure_date_grid(tab, accept_terms=accept_terms)
            if status != "GRID_READY":
                return "ENTRY_BLOCKED_AT_RELEASE_" + str(status)

        # Choose date and room once; stop on any ambiguous or disabled selector.
        for phase in ("date", "room"):
            code = await attempt_stage(tab, phase, day, priorities[0], attempts=8, mode=mode)
            print(f"{phase}: {code}")
            if code not in ("CLICKED", "ALREADY_SELECTED"):
                return "BLOCKED_" + code

        chosen_slot = None
        for slot in priorities:
            code = await attempt_stage(tab, "slot", day, slot, attempts=8, mode=mode)
            print(f"slot {slot}: {code}")
            if code in ("CLICKED", "ALREADY_SELECTED"):
                chosen_slot = slot
                break
            if code not in ("SLOT_DISABLED", "SLOT_NOT_BOOK_CLASS", "SLOT_NOT_UNIQUE"):
                return "BLOCKED_" + code
        if chosen_slot is None:
            return "NO_BOOKABLE_UI_SLOT"

        code = await attempt_stage(tab, "next", day, chosen_slot, attempts=8, mode=mode)
        print("next: " + code)
        if code != "CLICKED":
            return "BLOCKED_" + code

        # The final click is authorized only by --auto-submit.
        if not auto_submit:
            return "PREVIEW_STOPPED_BEFORE_SUBMIT"
        code = await submit_once_with_pointer(tab, day, chosen_slot, mode=mode, attempts=8)
        print("submit: " + code)
        if code != "CLICKED_ONCE":
            return "BLOCKED_" + code

        # Never retry the actual reservation submit. Inspect response only.
        for _ in range(12):
            await asyncio.sleep(0.25)
            code = await read_action(tab, "success", day, chosen_slot, mode)
            if code in ("SUCCESS_PAGE_MATCHED", "FAILURE_SHOWN"):
                return code
        return "SUBMITTED_SUCCESS_UNVERIFIED"
    finally:
        # Keep the real result visible for human verification and screenshots.
        if mode == "p03":
            await asyncio.to_thread(input, "請核對國圖畫面；按 Enter 關閉測試瀏覽器：")
        await browser.stop()


def main():
    parser = argparse.ArgumentParser(description="國圖音樂創作室／P03 單次自動預約")
    parser.add_argument("--date", required=True, type=date.fromisoformat,
                        help="目標日期 YYYY-MM-DD（必填）")
    parser.add_argument("--room", choices=ROOM_MODES, default="music",
                        help="music 音樂創作室（預設）或 p03 個人直播室測試")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--slots", default=None, help="音樂創作室三小時時段優先序")
    target.add_argument("--slot", default=None, help="P03 唯一的一小時測試時段")
    parser.add_argument("--auto-submit", action="store_true",
                        help="明確允許程式在核對日期、房間、時段後點一次最終「預約」")
    parser.add_argument("--now", action="store_true",
                        help="立刻執行，不等預設的 7 日前台北 00:00")
    parser.add_argument("--accept-terms", action="store_true",
                        help="本人已閱讀同意 OPEN LAB 條款，允許在入口點一次「同意 Agree」")
    args = parser.parse_args()
    if args.room == "p03":
        if args.slot is None or args.slot not in P03_SLOTS:
            parser.error("P03 測試必須提供 --slot，例如 13:00-14:00")
        priorities = (args.slot,)
    else:
        if args.slot is not None:
            parser.error("音樂創作室請用 --slots 指定三小時時段")
        priorities = parse_slot_priority(args.slots)
    room_name = ROOM if args.room == "music" else "個人直播室 P03"
    print(f"目標：{args.date.isoformat()}｜{room_name}｜優先序：{', '.join(priorities)}")
    print("注意：不繞驗證碼、不存帳密、不刷站；只會在此登入階段後操作。")
    if not args.auto_submit:
        print("未指定 --auto-submit，程式只會走到最後確認頁。")
    status = asyncio.run(autobook(args.date, priorities,
                                  auto_submit=args.auto_submit,
                                  now_mode=args.now, mode=args.room,
                                  accept_terms=args.accept_terms))
    print(json.dumps({"result": status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
