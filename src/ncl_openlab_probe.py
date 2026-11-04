#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only NCL OPEN LAB page probe.

Independent of the ticketing router. Does not click, reload, book, or send
requests to the reservation API. Requires the user to sign in manually.
"""

import argparse
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from reservation_browser import wait_until_browser_manually_closed

NCL_URL = "https://spms.ncl.edu.tw/"
NCL_HOST = "spms.ncl.edu.tw"
TAIPEI_TZ = timezone(timedelta(hours=8))
ROOM_NAME = "音樂創作室"
SLOTS = ("09:00-12:00", "13:00-16:00", "17:00-20:00")

# Only reads visible DOM nodes. It never triggers click, submit, or refresh.
PROBE_JS = r"""(() => {
  // The real NCL layout has a selected date tile, .space-box1 for a room,
  // and .time-box / .time-box2[data-param1] for time slots. No generic text-wide controls.
  const needles = __NEEDLES__;
  const dateLabel = needles[0];
  const roomLabel = needles[1];
  const times = needles.slice(2);
  const shownText = (el) => String(el.innerText || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.visibility !== "hidden" && style.display !== "none";
  };
  const isSelected = (el) => el.classList.contains("selected") ||
    el.getAttribute("aria-selected") === "true" ||
    el.getAttribute("aria-pressed") === "true";
  const isDisabled = (el) => el.classList.contains("disabled") ||
    el.classList.contains("is-disabled") ||
    el.classList.contains("unavailable") ||
    el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true";
  const candidate = (el, needle, kind) => ({
    tag: el.tagName.toLowerCase(),
    sample: needle, // Never emit arbitrary DOM text or personal details.
    selected: isSelected(el),
    disabled: isDisabled(el),
    clickable: kind === "slot" ?
               (el.classList.contains("time-box") || el.classList.contains("time-box2")) :
               kind === "room" ? el.classList.contains("space-box1") :
               (el.matches("button, a, [role='button']") || isSelected(el))
  });
  // The real date tile is div.date-box (selected tile adds class "selected").
  // Match the tile itself, never a nested weekday span or generic ancestor.
  const dateMatches = Array.from(document.querySelectorAll(".date-box"))
    .filter((el) => {
      const label = String(el.textContent || "").replace(/\s+/g, " ").trim();
      return visible(el) && label.startsWith(dateLabel) && label.length <= 80;
    });
  const roomMatches = Array.from(document.querySelectorAll(".space-box1"))
    .filter((el) => visible(el) && shownText(el).includes(roomLabel) &&
      shownText(el).length <= 80);
  const results = {};
  results[dateLabel] = dateMatches.slice(0, 8)
    .map((el) => candidate(el, dateLabel, "date"));
  results[roomLabel] = roomMatches.slice(0, 8)
    .map((el) => candidate(el, roomLabel, "room"));
  for (const time of times) {
    const matches = Array.from(document.querySelectorAll(".time-box[data-param1], .time-box2[data-param1]"))
      .filter((el) => visible(el) &&
        el.getAttribute("data-param1") === time);
    results[time] = matches.slice(0, 8)
      .map((el) => candidate(el, time, "slot"));
  }
  return {host: location.hostname, source: "ncl_structured_dom_v1", results};
})()"""


def next_open_date(now=None):
    """7-day date shown by the site; midnight release is user-observed."""
    current = now or datetime.now(TAIPEI_TZ)
    if current.tzinfo is None:
        raise ValueError("now must include timezone")
    return current.astimezone(TAIPEI_TZ).date() + timedelta(days=7)


def probe_needles(day, slot=None):
    """Exact target terms, with no personal or account information."""
    if not isinstance(day, date):
        raise TypeError("day must be a date")
    if slot is not None and slot not in SLOTS:
        raise ValueError("unsupported time slot")
    return [day.strftime("%m/%d"), ROOM_NAME, *([slot] if slot else SLOTS)]


def probe_script(day, slot=None):
    values = json.dumps(probe_needles(day, slot), ensure_ascii=False)
    return PROBE_JS.replace("__NEEDLES__", values)


async def inspect(day, priorities, save_evidence=False):
    # Delayed import permits offline stdlib tests without browser dependencies.
    import zendriver as uc

    browser = await uc.start(headless=False)
    try:
        tab = await browser.get(NCL_URL)
        await asyncio.to_thread(
            input,
            "請在開啟的瀏覽器手動登入國圖並進入多媒體創意實驗中心；"
            "完成後回到終端按 Enter 進行唯讀檢查：",
        )
        current_url = await tab.evaluate("location.href")
        if urlsplit(current_url).hostname != NCL_HOST:
            raise RuntimeError("Not on the official NCL reservation host")
        # Inspect all time windows once, then apply preference order locally.
        result = await tab.evaluate(probe_script(day))
        if not isinstance(result, dict) or result.get("host") != NCL_HOST:
            raise RuntimeError("DOM probe did not return a verified result")
        # Print only allowlisted target counts; no raw page text or account data.
        labels = probe_needles(day)
        counts = {label: len(result.get("results", {}).get(label, [])) for label in labels}
        print(json.dumps({"visible_target_counts": counts}, ensure_ascii=False, indent=2))
        from ncl_openlab_evidence import evidence_script, validate_evidence

        evidence = validate_evidence(await tab.evaluate(evidence_script()))
        print(json.dumps({"sanitized_time_dom_evidence": evidence},
                         ensure_ascii=False, indent=2))
        if save_evidence:
            from pathlib import Path
            from ncl_openlab_export import make_capture, save_capture

            root = Path(__file__).resolve().parents[1]
            capture = make_capture(evidence, day, priorities)
            saved = save_capture(root, capture)
            print(f"匿名時段證據已輸出：{saved}")
        from ncl_openlab_slots import plan_time_slots

        report = plan_time_slots(result, day, priorities)
        print(json.dumps({"time_slot_priority_plan": report}, ensure_ascii=False, indent=2))
        print("僅供時段偵測：OBSERVED_NOT_VERIFIED 不代表有空位。")
        print("唯讀檢查完成：沒有點選、提交預約或自動重新整理。")
    finally:
        # Let the user inspect the visible page (including any existing
        # reservation result) without an automatic Chrome shutdown.
        # Passive DevTools monitoring ends only when Chrome is closed manually.
        print("唯讀檢查已結束；Chrome 視窗保留，請自行關閉。此工具不會送出預約。")
        await wait_until_browser_manually_closed(browser)


def main():
    parser = argparse.ArgumentParser(description="國圖音樂創作室唯讀時段偵測")
    parser.add_argument(
        "--date", type=date.fromisoformat, default=next_open_date(),
        help="目標日期 YYYY-MM-DD（預設台灣今天 +7 天）",
    )
    preferences = parser.add_mutually_exclusive_group()
    preferences.add_argument(
        "--slot", choices=SLOTS, default=None,
        help="單一優先時段（保留舊版相容性）",
    )
    preferences.add_argument(
        "--slots", default=None,
        help="逗號分隔的時段優先順序，例如 17:00-20:00,13:00-16:00",
    )
    parser.add_argument(
        "--save-evidence", action="store_true",
        help="將匿名時段證據存成專案根目錄 ncl_openlab_evidence.json（不覆蓋舊檔）",
    )
    args = parser.parse_args()
    from ncl_openlab_slots import parse_slot_priority

    try:
        priorities = parse_slot_priority(args.slot if args.slot is not None else args.slots)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"目標：{args.date.isoformat()}｜{ROOM_NAME}｜時段優先序：{', '.join(priorities)}")
    asyncio.run(inspect(args.date, priorities, args.save_evidence))


if __name__ == "__main__":
    main()
