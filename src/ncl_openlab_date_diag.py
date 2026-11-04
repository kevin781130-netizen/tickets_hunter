#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only sanitized date/room selection diagnostic for the NCL P03 page.

Requires manual sign-in/navigation; never clicks, reloads or submits.
Reports only exact target match counts and allowlisted selection flags.
"""
import argparse
import asyncio
import json
from datetime import date
from urllib.parse import urlsplit

from ncl_openlab_probe import NCL_URL, NCL_HOST
from reservation_browser import wait_until_browser_manually_closed

DIAG_JS = r"""(() => {
  const target = __TARGET__;
  if (location.hostname !== "spms.ncl.edu.tw")
    return {host: location.hostname, status: "WRONG_HOST"};
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 &&
      style.visibility !== "hidden" && style.display !== "none";
  };
  const clean = (el) => String(el.innerText || "").replace(/\s+/g, " ").trim();
  const classes = ["selected", "book", "active", "is-selected", "chosen", "current"];
  const flags = (el) => ({
    class_flags: classes.filter(c => el.classList.contains(c)),
    parent_class_flags: el.parentElement
      ? classes.filter(c => el.parentElement.classList.contains(c)) : [],
    aria_selected: el.getAttribute("aria-selected") === "true",
    aria_pressed: el.getAttribute("aria-pressed") === "true",
    data_selected: el.getAttribute("data-selected") === "true",
    visible: visible(el),
  });
  const dates = Array.from(document.querySelectorAll(".date-box")).filter(visible);
  const rooms = Array.from(document.querySelectorAll(".space-box1")).filter(visible);
  const matchedDates = dates.filter(el => clean(el).startsWith(target.shortDate));
  const matchedRooms = rooms.filter(el => /^P03(?:\s|$)/.test(clean(el)));
  return {
    host: location.hostname,
    status: "READ_ONLY",
    expected_date: target.shortDate,
    date_grid_total: Math.min(dates.length, 100),
    date_match_count: Math.min(matchedDates.length, 100),
    date_flags: matchedDates.slice(0, 3).map(flags),
    room_grid_total: Math.min(rooms.length, 100),
    p03_match_count: Math.min(matchedRooms.length, 100),
    p03_flags: matchedRooms.slice(0, 3).map(flags)
  };
})()"""


def diagnostic_script(day):
    if not isinstance(day, date) or type(day) is not date:
        raise ValueError("invalid target date")
    return DIAG_JS.replace("__TARGET__",
                           json.dumps({"shortDate": day.strftime("%m/%d")}))


def validate_diagnostic(data, day):
    if not isinstance(data, dict) or data.get("host") != NCL_HOST:
        raise ValueError("not on official NCL host")
    if data.get("status") != "READ_ONLY" or data.get("expected_date") != day.strftime("%m/%d"):
        raise ValueError("unexpected diagnostic status")
    output = {"status": "READ_ONLY", "date": day.isoformat()}
    allowed = {"selected", "book", "active", "is-selected", "chosen", "current"}
    for field in ("date_grid_total", "date_match_count",
                  "room_grid_total", "p03_match_count"):
        value = data.get(field)
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError("invalid DOM count")
        output[field] = value
    for name, count in (("date_flags", "date_match_count"),
                        ("p03_flags", "p03_match_count")):
        rows = data.get(name)
        if not isinstance(rows, list) or len(rows) != min(output[count], 3):
            raise ValueError("invalid flag rows")
        clean_rows = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid flags")
            item = {}
            for field in ("class_flags", "parent_class_flags"):
                value = row.get(field)
                if not isinstance(value, list) or any(x not in allowed for x in value):
                    raise ValueError("non-allowlisted CSS flag")
                item[field] = sorted(set(value))
            for field in ("aria_selected", "aria_pressed", "data_selected", "visible"):
                if type(row.get(field)) is not bool:
                    raise ValueError("invalid DOM boolean")
                item[field] = row[field]
            clean_rows.append(item)
        output[name] = clean_rows
    return output


async def inspect(day):
    import zendriver as uc
    browser = await uc.start(headless=False)
    try:
        tab = await browser.get(NCL_URL)
        await asyncio.to_thread(
            input, "請手動登入，前往 P03 預約日期頁，點選目標日期；完成後回此按 Enter：")
        url = await tab.evaluate("location.href")
        if urlsplit(url).hostname != NCL_HOST:
            raise RuntimeError("WRONG_HOST: not on official reservation page")
        result = validate_diagnostic(await tab.evaluate(diagnostic_script(day)), day)
        print(json.dumps({"ncl_date_selection_diagnostic": result},
                         ensure_ascii=False, indent=2))
        print("只讀取日期與房間的匿名選取標記；沒有送出預約。")
    finally:
        print("Chrome 保留供檢查；關閉這個 Chrome 視窗以結束診斷。")
        await wait_until_browser_manually_closed(browser)


def main():
    parser = argparse.ArgumentParser(description="國圖 P03 日期狀態唯讀診斷")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    print(f"唯讀診斷：{args.date.isoformat()}｜P03｜不會執行預約")
    asyncio.run(inspect(args.date))


if __name__ == "__main__":
    main()
