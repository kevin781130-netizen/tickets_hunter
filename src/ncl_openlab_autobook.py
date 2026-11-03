#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot, opt-in NCL music room booking through the visible browser UI.

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
    .filter(el => cleanText(el).includes(task.room)));
  const slotTile = () => exactOne(from(".time-box2[data-param1]")
    .filter(el => el.getAttribute("data-param1") === task.slot));
  const chosen = (el) => el && el.classList.contains("selected");
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
    if (!tile.classList.contains("book")) return result("SLOT_NOT_BOOK_CLASS");
    if (chosen(tile)) return result("ALREADY_SELECTED");
    tile.click(); return result("CLICKED");
  }
  const cta = (word) => {
    const matches = from("button, a, div, [role='button'], input[type='button'], input[type='submit']")
      .filter(el => cleanText(el) === word ||
        (el.matches("input") && String(el.value || "").trim() === word));
    // Prefer the innermost exact-text node to avoid both parent and child clicks.
    return exactOne(matches.filter(el => !matches.some(child =>
      child !== el && el.contains(child))));
  };
  if (task.phase === "next") {
    if (!chosen(dateTile()) || !chosen(roomTile()) ||
        !chosen(slotTile())) return result("TARGET_NOT_SELECTED");
    const button = cta("下一步");
    if (!button || disabled(button)) return result("NEXT_NOT_ACTIONABLE");
    button.click(); return result("CLICKED");
  }
  // Final confirmation page may no longer have .date-box and .space-box1.
  // Compare all three target facts in the rendered visible page, not form values.
  const summary = () => {
    const display = String(document.body.innerText || "");
    return display.includes(task.fullDate) &&
      display.includes(task.room) && display.includes(task.slot);
  };
  if (task.phase === "submit") {
    if (window.__nclOneShotSubmit === true) return result("ALREADY_SUBMITTED");
    if (!summary()) return result("SUMMARY_MISMATCH");
    const button = cta("預約");
    if (!button || disabled(button)) return result("SUBMIT_NOT_ACTIONABLE");
    window.__nclOneShotSubmit = true; // Never duplicate a final submit on this page.
    button.click(); return result("CLICKED_ONCE");
  }
  if (task.phase === "success") {
    const display = String(document.body.innerText || "");
    if (display.includes("預約成功") &&
        display.includes(task.fullDate) &&
        display.includes(task.slot) &&
        display.includes(task.room)) return result("SUCCESS_PAGE_MATCHED");
    if (display.includes("預約失敗")) return result("FAILURE_SHOWN");
    return result("SUCCESS_NOT_VERIFIED");
  }
  return result("UNKNOWN_PHASE");
})()"""


def action_script(phase, day, slot):
    if phase not in PHASES:
        raise ValueError("invalid phase")
    if not isinstance(day, date) or isinstance(day, datetime) or slot not in VALID_SLOTS:
        raise ValueError("invalid music-room target")
    data = {"phase": phase, "shortDate": day.strftime("%m/%d"),
            "fullDate": day.strftime("%Y/%m/%d"), "room": ROOM, "slot": slot}
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


async def at_official_host(tab):
    url = await tab.evaluate("location.href")
    return urlsplit(url).hostname == NCL_HOST


async def read_action(tab, phase, day, slot):
    if not await at_official_host(tab):
        raise RuntimeError("NOT_OFFICIAL_NCL_HOST")
    response = await tab.evaluate(action_script(phase, day, slot))
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


async def attempt_stage(tab, phase, day, slot, attempts=6):
    """Only reread the local DOM; no extra HTTP requests or page refreshes."""
    transient = {
        "date": {"DATE_NOT_UNIQUE"},
        "room": {"ROOM_NOT_UNIQUE"},
        "slot": {"SLOT_NOT_UNIQUE"},
        "next": {"NEXT_NOT_ACTIONABLE", "TARGET_NOT_SELECTED"},
        "submit": {"SUBMIT_NOT_ACTIONABLE", "SUMMARY_MISMATCH"},
    }.get(phase, set())
    for i in range(attempts):
        code = await read_action(tab, phase, day, slot)
        if code not in transient or i == attempts - 1:
            return code
        await asyncio.sleep(0.2)
    return code


async def autobook(day, priorities, *, auto_submit, now_mode=False):
    import zendriver as uc

    browser = await uc.start(headless=False)
    try:
        tab = await browser.get(NCL_URL)
        print("在此瀏覽器手動登入並開啟多媒體創意實驗中心的日期選擇畫面。")
        await asyncio.to_thread(input, "登入及進入頁面後按 Enter 啟動單次自動預約：")
        if not await at_official_host(tab):
            raise RuntimeError("NOT_OFFICIAL_NCL_HOST")
        if not await tab.evaluate('document.querySelectorAll(".date-box").length > 0'):
            raise RuntimeError("DATE_GRID_NOT_VISIBLE")
        if not now_mode:
            remaining = seconds_until_release(day)
            if not 0 <= remaining <= 900:
                raise RuntimeError("RELEASE_OUTSIDE_15_MINUTE_WINDOW")
            print("等待國圖預約開放時間（台北時間），到點只刷新一次。")
            if remaining:
                await asyncio.sleep(remaining)
            await tab.reload(ignore_cache=False)
            await tab.wait_for_ready_state(until="interactive", timeout=10)
            await asyncio.sleep(0.15)

        # Choose date and room once; stop on any ambiguous or disabled selector.
        for phase in ("date", "room"):
            code = await attempt_stage(tab, phase, day, priorities[0], attempts=8)
            print(f"{phase}: {code}")
            if code not in ("CLICKED", "ALREADY_SELECTED"):
                return "BLOCKED_" + code

        chosen_slot = None
        for slot in priorities:
            code = await attempt_stage(tab, "slot", day, slot, attempts=8)
            print(f"slot {slot}: {code}")
            if code in ("CLICKED", "ALREADY_SELECTED"):
                chosen_slot = slot
                break
            if code not in ("SLOT_DISABLED", "SLOT_NOT_BOOK_CLASS", "SLOT_NOT_UNIQUE"):
                return "BLOCKED_" + code
        if chosen_slot is None:
            return "NO_BOOKABLE_UI_SLOT"

        code = await attempt_stage(tab, "next", day, chosen_slot, attempts=8)
        print("next: " + code)
        if code != "CLICKED":
            return "BLOCKED_" + code

        # The final click is authorized only by --auto-submit.
        if not auto_submit:
            return "PREVIEW_STOPPED_BEFORE_SUBMIT"
        code = await attempt_stage(tab, "submit", day, chosen_slot, attempts=8)
        print("submit: " + code)
        if code != "CLICKED_ONCE":
            return "BLOCKED_" + code

        # Never retry the actual reservation submit. Inspect response only.
        for _ in range(12):
            await asyncio.sleep(0.25)
            code = await read_action(tab, "success", day, chosen_slot)
            if code in ("SUCCESS_PAGE_MATCHED", "FAILURE_SHOWN"):
                return code
        return "SUBMITTED_SUCCESS_UNVERIFIED"
    finally:
        await browser.stop()


def main():
    parser = argparse.ArgumentParser(description="國圖音樂創作室單次自動預約")
    parser.add_argument("--date", required=True, type=date.fromisoformat,
                        help="目標日期 YYYY-MM-DD（必填）")
    parser.add_argument("--slots", default=None,
                        help="三小時時段優先序，逗號分隔")
    parser.add_argument("--auto-submit", action="store_true",
                        help="明確允許程式在核對日期、房間、時段後點一次最終「預約」")
    parser.add_argument("--now", action="store_true",
                        help="立刻執行，不等預設的 7 日前台北 00:00")
    args = parser.parse_args()
    priorities = parse_slot_priority(args.slots)
    print(f"目標：{args.date.isoformat()}｜{ROOM}｜優先序：{', '.join(priorities)}")
    print("注意：不繞驗證碼、不存帳密、不刷站；只會在此登入階段後操作。")
    if not args.auto_submit:
        print("未指定 --auto-submit，程式只會走到最後確認頁。")
    status = asyncio.run(autobook(args.date, priorities,
                                  auto_submit=args.auto_submit, now_mode=args.now))
    print(json.dumps({"result": status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
