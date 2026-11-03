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

NCL_URL = "https://spms.ncl.edu.tw/"
NCL_HOST = "spms.ncl.edu.tw"
TAIPEI_TZ = timezone(timedelta(hours=8))
ROOM_NAME = "音樂創作室"
SLOTS = ("09:00-12:00", "13:00-16:00", "17:00-20:00")

# Only reads visible DOM nodes. It never triggers click, submit, or refresh.
PROBE_JS = r"""(() => {
  const needles = __NEEDLES__;
  const all = Array.from(document.querySelectorAll("*")).slice(0, 20000);
  const shownText = (el) => String(el.innerText || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const locate = (needle) => {
    const matching = all.filter((el) => {
      const s = shownText(el);
      return visible(el) && s.includes(needle) && s.length <= 100;
    });
    const smallest = matching.filter((el) =>
      !Array.from(el.children).some((child) => {
        const s = shownText(child);
        return s.includes(needle) && s.length <= 100 && visible(child);
      })
    );
    return smallest.slice(0, 8).map((el) => ({
      tag: el.tagName.toLowerCase(),
      clickable: Boolean(el.closest("button, a, [role='button'], label, input[type='radio'], input[type='checkbox']")),
      disabled: Boolean(el.closest("[disabled], [aria-disabled='true'], .disabled, .is-disabled")),
      selected: el.getAttribute("aria-selected") === "true" ||
                el.getAttribute("aria-pressed") === "true",
      sample: shownText(el).slice(0, 60)
    }));
  };
  return {
    host: location.hostname,
    path: location.pathname,
    results: Object.fromEntries(needles.map((n) => [n, locate(n)]))
  };
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


async def inspect(day, priorities):
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        from ncl_openlab_slots import plan_time_slots

        report = plan_time_slots(result, day, priorities)
        print(json.dumps({"time_slot_priority_plan": report}, ensure_ascii=False, indent=2))
        print("僅供時段偵測：OBSERVED_NOT_VERIFIED 不代表有空位。")
        print("唯讀檢查完成：沒有點選、提交預約或自動重新整理。")
    finally:
        await browser.stop()


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
    args = parser.parse_args()
    from ncl_openlab_slots import parse_slot_priority

    try:
        priorities = parse_slot_priority(args.slot if args.slot is not None else args.slots)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"目標：{args.date.isoformat()}｜{ROOM_NAME}｜時段優先序：{', '.join(priorities)}")
    asyncio.run(inspect(args.date, priorities))


if __name__ == "__main__":
    main()
