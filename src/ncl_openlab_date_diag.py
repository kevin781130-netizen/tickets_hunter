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
  // P01 has appeared as .space-box1 in actual NCL markup. Search all three
  // restricted room classes, never generic page text or personal data.
  const roomClasses = ["space-box1", "space-box2", "space-box3"];
  const rooms = Array.from(document.querySelectorAll(
    ".space-box1, .space-box2, .space-box3")).filter(visible);
  const roomCode = (el) => {
    const text = clean(el);
    const found = text.match(/^P0[123](?=\s|$)/);
    return found ? found[0] : null;
  };
  // Inspect only whitelisted room-code presence; never return page text,
  // attribute contents, HTML, account details, or arbitrary identifiers.
  const knownCodes = ["P01", "P02", "P03"];
  const codeSignals = (text) => {
    const normalized = String(text || "").normalize("NFKC");
    return knownCodes.filter(code => new RegExp(
      "(^|[^A-Za-z0-9])" + code + "(?![A-Za-z0-9])").test(normalized));
  };
  const tileSignals = (el) => {
    const rendered = String(el.innerText || "");
    const content = String(el.textContent || "");
    const aria = String(el.getAttribute("aria-label") || "");
    return {
      classes: roomClasses.filter(c => el.classList.contains(c)),
      selected: el.classList.contains("selected"),
      rendered_has_text: Boolean(rendered.trim()),
      content_has_text: Boolean(content.trim()),
      rendered_codes_anywhere: codeSignals(rendered),
      content_codes_anywhere: codeSignals(content),
      aria_codes_anywhere: codeSignals(aria),
      has_broadcast_label: (
        rendered.includes("個人直播室") ||
        content.includes("個人直播室")),
      has_music_label: (
        rendered.includes("音樂創作室") ||
        content.includes("音樂創作室")),
    };
  };
  const matchedDates = dates.filter(el => clean(el).startsWith(target.shortDate));
  const matchedRooms = rooms.filter(el => roomCode(el) === "P03");
  const roomCodes = ["P01", "P02", "P03"];

  return {
    host: location.hostname,
    status: "READ_ONLY",
    expected_date: target.shortDate,
    iframe_count: Math.min(document.querySelectorAll("iframe").length, 100),
    date_grid_total: Math.min(dates.length, 100),
    date_match_count: Math.min(matchedDates.length, 100),
    date_flags: matchedDates.slice(0, 3).map(flags),
    room_grid_total: Math.min(rooms.length, 100),
    room_tile_signals: rooms.slice(0, 3).map(tileSignals),
    room_class_counts: Object.fromEntries(
      roomClasses.map(name => [name, Math.min(rooms.filter(
        el => el.classList.contains(name)).length, 100)])),
    room_code_counts: Object.fromEntries(
      roomCodes.map(code => [code, Math.min(rooms.filter(
        el => roomCode(el) === code).length, 100)])),
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
    for field in ("iframe_count", "date_grid_total", "date_match_count",
                  "room_grid_total", "p03_match_count"):
        value = data.get(field)
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError("invalid DOM count")
        output[field] = value
    signals = data.get("room_tile_signals")
    if not isinstance(signals, list) or len(signals) != min(output["room_grid_total"], 3):
        raise ValueError("invalid room tile signals")
    output["room_tile_signals"] = []
    class_allowlist = {"space-box1", "space-box2", "space-box3"}
    codes_allowlist = {"P01", "P02", "P03"}
    for row in signals:
        if not isinstance(row, dict):
            raise ValueError("invalid room tile row")
        classes = row.get("classes")
        if not isinstance(classes, list) or any(
                type(v) is not str or v not in class_allowlist for v in classes):
            raise ValueError("unknown room class")
        result = {"classes": sorted(set(classes))}
        for field in ("selected", "rendered_has_text", "content_has_text",
                      "has_broadcast_label", "has_music_label"):
            if type(row.get(field)) is not bool:
                raise ValueError("invalid room boolean")
            result[field] = row[field]
        for field in ("rendered_codes_anywhere", "content_codes_anywhere",
                      "aria_codes_anywhere"):
            values = row.get(field)
            if not isinstance(values, list) or any(
                    type(v) is not str or v not in codes_allowlist
                    for v in values):
                raise ValueError("unexpected room-code signal")
            result[field] = sorted(set(values))
        output["room_tile_signals"].append(result)
    for key, labels in (
            ("room_class_counts", ("space-box1", "space-box2", "space-box3")),
            ("room_code_counts", ("P01", "P02", "P03"))):
        group = data.get(key)
        if not isinstance(group, dict) or set(group) != set(labels):
            raise ValueError("invalid room diagnostic category")
        if any(type(group[label]) is not int or not 0 <= group[label] <= 100
               for label in labels):
            raise ValueError("invalid room diagnostic count")
        output[key] = {label: group[label] for label in labels}
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


async def collect_browser_diagnostics(browser, day):
    """Read every NCL page tab; never confuse the initial tab with a popup.

    Zendriver's browser.tabs enumerates current page targets. Only tabs whose
    target metadata points to the official NCL origin are evaluated. Other
    tabs and URLs are never inspected or included in output.
    """
    await browser.update_targets()
    page_tabs = list(browser.tabs)
    results = []
    for index, page in enumerate(page_tabs):
        url = str(getattr(getattr(page, "target", None), "url", "") or "")
        parsed = urlsplit(url)
        if parsed.hostname != NCL_HOST:
            continue
        kind = {
            "/NLT/co/media_discussion.jsp": "booking",
            "/NLT/co/multimedia.jsp": "status",
        }.get(parsed.path, "other_ncl_page")
        try:
            result = validate_diagnostic(
                await page.evaluate(diagnostic_script(day)), day)
        except Exception:
            # A tab can close or navigate while we read. No page data leaks.
            results.append({"tab_index": index, "page_kind": kind,
                            "status": "READ_FAILED"})
            continue
        results.append({"tab_index": index, "page_kind": kind, **result})
    return {
        "total_open_tabs": min(len(page_tabs), 100),
        "official_ncl_tabs": len(results),
        "pages": results,
        "date_grid_detected": any(
            row.get("date_grid_total", 0) > 0 for row in results),
    }


async def inspect(day):
    import zendriver as uc
    browser = await uc.start(headless=False)
    try:
        await browser.get(NCL_URL)
        await asyncio.to_thread(
            input, "請在程式開啟的 Chrome 視窗手動登入，前往 P03 預約日期頁，"
                   "點選目標日期；完成後回此按 Enter：")
        result = await collect_browser_diagnostics(browser, day)
        print(json.dumps({"ncl_date_selection_diagnostic": result},
                         ensure_ascii=False, indent=2))
        if not result["date_grid_detected"]:
            print("尚未在程式控制的任何國圖分頁找到日期格。"
                  "請確認使用的是程式開啟的 Chrome，而不是原本的 Chrome。")
        print("只讀取官方國圖分頁的匿名選取標記；沒有送出預約。")
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
