#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only per-room DOM inventory for unverified OPEN LAB space categories.

Use the Chrome instance opened by this script. Manually log in, open the
requested space's date/room/slot grid in the SAME tab, then press Enter.
No clicks, refreshes, bookings, cookies, profiles, HTML or user data collected.
"""
import argparse
import asyncio
import json

from ncl_openlab_room_catalog import (
    OFFICIAL_OVERVIEW_URL, ROOM_CATALOG, ROOM_CHOICES,
)
from reservation_browser import wait_until_browser_manually_closed

ROOM_DIAG_JS = r"""(() => {
  if (location.hostname !== "spms.ncl.edu.tw")
    return {status: "WRONG_HOST"};
  const visible = el => {
    const r = el.getBoundingClientRect(), style = getComputedStyle(el);
    return r.width > 0 && r.height > 0 &&
      style.display !== "none" && style.visibility !== "hidden";
  };
  const roomTiles = Array.from(document.querySelectorAll(
    ".space-box, .space-box1, .space-box2, .space-box3")).filter(visible);
  const slotTiles = Array.from(document.querySelectorAll(
    ".time-box[data-param1], .time-box2[data-param1]")).filter(visible);
  const dates = Array.from(document.querySelectorAll(".date-box")).filter(visible);
  const flags = el => ({
    selected: el.classList.contains("selected"),
    book: el.classList.contains("book"),
    disabled: ["disabled","reserving","unavailable","is-disabled"].some(
      c => el.classList.contains(c)) ||
      el.getAttribute("aria-disabled") === "true"
  });
  // Never return text/HTML or arbitrary attributes. Only codes whose bilingual
  // child labels and visible text agree; no session/person/booking identifiers.
  const code = el => {
    const labels = Array.from(el.querySelectorAll(
      "span[data-en][data-zh]")).filter(visible);
    const candidates = labels.map(label => {
      const en = label.getAttribute("data-en"),
            zh = label.getAttribute("data-zh"),
            text = String(label.innerText || "").trim();
      return en === zh && en === text && /^[A-Z]{1,3}[0-9]{1,3}$/.test(en)
        ? en : null;
    }).filter(Boolean);
    return candidates.length === 1 ? candidates[0] : null;
  };
  const slots = slotTiles.map(el => ({
    slot: el.getAttribute("data-param1"),
    kind: el.classList.contains("time-box2") ? "time-box2" : "time-box",
    ...flags(el)
  })).filter(item => /^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$/.test(item.slot));
  return {
    status: "READ_ONLY",
    date_tile_count: Math.min(dates.length, 100),
    selected_date_count: Math.min(dates.filter(el =>
      el.classList.contains("selected")).length, 100),
    room_tile_count: Math.min(roomTiles.length, 100),
    rooms: roomTiles.slice(0, 24).map(el => ({
      code: code(el),
      kind: ["space-box","space-box1","space-box2","space-box3"]
        .find(cls => el.classList.contains(cls)) || "unknown",
      ...flags(el)
    })),
    time_tile_count: Math.min(slotTiles.length, 100),
    slots: slots.slice(0, 30),
    note: "DOM_STATES_ONLY_NOT_AVAILABILITY"
  };
})()"""


def validate_report(report):
    if not isinstance(report, dict):
        return {"status": "INVALID_RESULT"}
    if report.get("status") != "READ_ONLY":
        return {"status": "WRONG_HOST_OR_INVALID"}
    rooms = report.get("rooms")
    slots = report.get("slots")
    if not isinstance(rooms, list) or not isinstance(slots, list):
        return {"status": "INVALID_RESULT"}
    if len(rooms) > 24 or len(slots) > 30:
        return {"status": "INVALID_RESULT"}
    import re
    for item in rooms:
        if not isinstance(item, dict) or set(item) != {
            "code", "kind", "selected", "book", "disabled"}:
            return {"status": "INVALID_RESULT"}
        code = item["code"]
        if code is not None and not re.fullmatch(r"[A-Z]{1,3}[0-9]{1,3}", code):
            return {"status": "INVALID_RESULT"}
        if item["kind"] not in (
            "space-box","space-box1","space-box2","space-box3"):
            return {"status": "INVALID_RESULT"}
    for item in slots:
        if not isinstance(item, dict) or set(item) != {
            "slot", "kind", "selected", "book", "disabled"}:
            return {"status": "INVALID_RESULT"}
        if not re.fullmatch(
            r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d",
            item["slot"]):
            return {"status": "INVALID_RESULT"}
        if item["kind"] not in ("time-box", "time-box2"):
            return {"status": "INVALID_RESULT"}
    if any(type(item[key]) is not bool for item in (*rooms,*slots)
           for key in ("selected", "book", "disabled")):
        return {"status": "INVALID_RESULT"}
    for key in ("date_tile_count", "selected_date_count",
                "room_tile_count", "time_tile_count"):
        if type(report.get(key)) is not int or not 0 <= report[key] <= 100:
            return {"status": "INVALID_RESULT"}
    return report


async def inspect(room):
    import zendriver as uc
    browser = await uc.start(headless=False)
    try:
        tab = await browser.get(OFFICIAL_OVERVIEW_URL)
        await asyncio.to_thread(
            input, f"登入並在同一 Chrome 分頁開啟「{ROOM_CHOICES[room]}」"
                   "的日期／房間／時段畫面；完成後按 Enter 唯讀採集：")
        result = validate_report(await tab.evaluate(ROOM_DIAG_JS))
        print(json.dumps({"target_category": ROOM_CHOICES[room],
                          "ncl_room_dom_read_only": result},
                         ensure_ascii=False, indent=2))
        print("沒有點擊、送出、登入資訊讀取或重新整理。")
    finally:
        print("請關閉此 Chrome 視窗結束診斷，無需 Ctrl+C。")
        await wait_until_browser_manually_closed(browser)


def main():
    parser = argparse.ArgumentParser(description="國圖全空間安全唯讀 DOM 診斷")
    parser.add_argument("--room", choices=tuple(
        key for key, spec in ROOM_CATALOG.items()
        if spec.automation == "needs_live_dom"), required=True)
    args = parser.parse_args()
    asyncio.run(inspect(args.room))


if __name__ == "__main__":
    main()
