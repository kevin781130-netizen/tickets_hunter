#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only room inventory and flow classification for NCL OPEN LAB.

Run it inside YOUR OWN logged-in browser session. It never clicks, submits,
refreshes or calls any API: you navigate by hand to each room's selection
screen and press Enter to capture what is visibly there. The result is
classified against ncl_openlab_rooms.json and, for rooms the config does not
know yet, a DRAFT entry is printed.

Honest limit: one static snapshot cannot tell whether a 'book' class means
"bookable before the click" or "selected after the click" (that exact ambiguity
caused the P03 bug). So a draft is only a candidate: it carries TODO markers
and NOT_VERIFIED evidence, and the config loader refuses to activate it until
a human fills them in and a live check is done.
"""
import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from ncl_openlab_diag import TAIPEI_TZ
from ncl_openlab_guard import NCL_HOST
from ncl_openlab_probe import NCL_URL
from ncl_openlab_rooms import get_registry

SOURCE = "ncl_inventory_v1"
SLOT_RE = re.compile(r"^\d{2}:\d{2}-\d{2}:\d{2}$")
KIND_RE = re.compile(r"^time-box\d*$")
DATE_RE = re.compile(r"^\d{2}/\d{2}$")
MAX_ITEMS = 60

INVENTORY_JS = r"""(() => {
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
  const kindOf = (el) => Array.from(el.classList).find(c => /^time-box\d*$/.test(c)) || "";
  if (location.hostname !== "spms.ncl.edu.tw") return {host: "OTHER", source: "ncl_inventory_v1"};
  return {
    host: location.hostname, source: "ncl_inventory_v1", path: location.pathname,
    status_labels: from(".lab-item .lab-name[data-zh]").slice(0, 60).map(el => ({
      label: String(el.getAttribute("data-zh") || "").slice(0, 40),
      disabled: disabled(el.closest(".lab-item") || el)})),
    dates: from(".date-box").slice(0, 60).map(el => cleanText(el).slice(0, 5)),
    rooms: from(".space-box1").slice(0, 60).map(el => ({
      label: cleanText(el).slice(0, 40),
      selected: el.classList.contains("selected"), disabled: disabled(el)})),
    slots: from("[data-param1]").slice(0, 60).map(el => ({
      label: String(el.getAttribute("data-param1") || "").slice(0, 20),
      kind: kindOf(el), selected: el.classList.contains("selected"),
      book: el.classList.contains("book"), disabled: disabled(el)}))
  };
})()"""


def validate_inventory(raw):
    """Return a sanitized copy or None (fail closed on any surprise)."""
    if not isinstance(raw, dict) or raw.get("host") != NCL_HOST or raw.get("source") != SOURCE:
        return None
    clean = {"path": str(raw.get("path", ""))[:80]}
    try:
        clean["status_labels"] = [
            {"label": str(i["label"])[:40], "disabled": bool(i["disabled"])}
            for i in raw["status_labels"][:MAX_ITEMS] if str(i["label"]).strip()]
        clean["dates"] = [d for d in raw["dates"][:MAX_ITEMS] if DATE_RE.match(str(d))]
        clean["rooms"] = [
            {"label": re.sub(r"\s+", " ", str(i["label"])).strip()[:40],
             "selected": bool(i["selected"]), "disabled": bool(i["disabled"])}
            for i in raw["rooms"][:MAX_ITEMS] if str(i["label"]).strip()]
        clean["slots"] = [
            {"label": str(i["label"]), "kind": str(i["kind"]),
             "selected": bool(i["selected"]), "book": bool(i["book"]),
             "disabled": bool(i["disabled"])}
            for i in raw["slots"][:MAX_ITEMS]
            if SLOT_RE.match(str(i["label"])) and (i["kind"] == "" or KIND_RE.match(str(i["kind"])))]
    except (KeyError, TypeError, IndexError):
        return None
    return clean


def slot_hours(label):
    start, end = label.split("-")
    to_minutes = lambda t: int(t[:2]) * 60 + int(t[3:])  # noqa: E731
    return (to_minutes(end) - to_minutes(start)) / 60


def summarize_inventory(raw, registry=None):
    """Classify one validated snapshot against the configured rooms and flows."""
    registry = registry or get_registry()
    data = validate_inventory(raw)
    if data is None:
        return {"valid": False, "reason": "INVENTORY_RESULT_INVALID"}
    entry_labels = {p.entry_label: p.key for p in registry.rooms.values()}
    rooms = []
    for room in data["rooms"]:
        matches = [p.key for p in registry.rooms.values() if p.tile_matches(room["label"])]
        rooms.append({**room, "configured_as": matches[0] if len(matches) == 1 else None,
                      "ambiguous": len(matches) > 1})
    kinds = {}
    for slot in data["slots"]:
        kinds.setdefault(slot["kind"] or "UNKNOWN_KIND", []).append(slot)
    slot_groups = []
    for kind, items in sorted(kinds.items()):
        selector = f".{kind}[data-param1]"
        flow = next((f for f in registry.flows.values() if f.slot_selector == selector), None)
        durations = sorted({slot_hours(s["label"]) for s in items})
        slot_groups.append({
            "kind": kind, "selector": selector, "count": len(items),
            "durations_hours": durations,
            "labels": [s["label"] for s in items],
            "book_seen": any(s["book"] for s in items),
            "flow_candidate": flow.name if flow else None,
            # The sign of 'book' (before vs after click) is not observable here.
            "confidence": "SELECTOR_ONLY_NEEDS_LIVE_CHECK" if flow else "NEW_FLOW_UNVERIFIED",
        })
    status = [{**item, "configured_as": entry_labels.get(item["label"])}
              for item in data["status_labels"]]
    unconfigured_rooms = [r["label"] for r in rooms if r["configured_as"] is None]
    unconfigured_status = [i["label"] for i in status if i["configured_as"] is None]
    return {"valid": True, "path": data["path"], "dates": data["dates"],
            "status_labels": status, "rooms": rooms, "slot_groups": slot_groups,
            "unconfigured_rooms": unconfigured_rooms,
            "unconfigured_status_labels": unconfigured_status}


def draft_room_entry(room_label, slot_labels, flow_name, existing_keys=()):
    """A config DRAFT for an unknown room. Intentionally cannot be activated as-is."""
    token = re.match(r"^([A-Za-z]\d{1,3})(?:\s|$)", room_label)
    base = token.group(1).lower() if token else "room"
    key, n = base, 1
    while key in existing_keys:
        n += 1
        key = f"{base}_{n}"
    tile = ({"kind": "regex", "value": f"^{token.group(1)}(?:\\s|$)"} if token
            else {"kind": "includes", "value": room_label})
    return key, {
        "label": room_label, "ui_label": f"{room_label}（TODO 填入時段長度）",
        "entry_label": "TODO 填入多媒體空間現況頁的 data-zh 名稱",
        "flow": flow_name or "TODO 先定義新的 flow",
        "tile_match": tile,
        "summary_match": {"text_all": ["TODO 填入最後確認頁上的房型名稱"], "regex_all": []},
        "sample_tile_label": room_label,
        "slots": {"kind": "list", "values": sorted(set(slot_labels))},
        "default_all_slots": False, "single_slot_option": False,
        "submit_requires_ack": True,
        "evidence": {"live": "NOT_VERIFIED",
                     "live_notes": "TODO 實機走完一次流程後再改為 LIVE_VERIFIED",
                     "source": "ncl_openlab_inventory.py 草稿"},
    }


def build_drafts(summary, registry=None):
    registry = registry or get_registry()
    if not summary.get("valid"):
        return {}
    drafts, used = {}, set(registry.keys)
    slot_labels = [s for g in summary["slot_groups"] for s in g["labels"]]
    flows = {g["flow_candidate"] for g in summary["slot_groups"]}
    flow_name = flows.pop() if len(flows) == 1 else None
    for label in summary["unconfigured_rooms"]:
        key, entry = draft_room_entry(label, slot_labels, flow_name, used)
        used.add(key)
        drafts[key] = entry
    return drafts


async def capture(tab):
    url = await tab.evaluate("location.href")
    if urlsplit(url).hostname != NCL_HOST:
        raise RuntimeError("NOT_OFFICIAL_NCL_HOST")
    return await tab.evaluate(INVENTORY_JS)


async def run(report_dir):
    import zendriver as uc

    browser = await uc.start(headless=False)
    snapshots = []
    try:
        tab = await browser.get(NCL_URL)
        print("在此瀏覽器手動登入，並自行切換到想盤點的房型選擇畫面。")
        print("程式只讀取畫面上可見的類別與時段標籤，不會點擊、刷新或送出。")
        while True:
            answer = await asyncio.to_thread(
                input, "到達房型畫面後按 Enter 擷取；輸入 q 結束：")
            if answer.strip().lower() == "q":
                break
            summary = summarize_inventory(await capture(tab))
            snapshots.append(summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        folder = Path(report_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(TAIPEI_TZ).strftime("%Y%m%d_%H%M%S")
        drafts = {}
        for snap in snapshots:
            drafts.update(build_drafts(snap))
        out = folder / f"ncl_inventory_{stamp}.json"
        out.write_text(json.dumps({"snapshots": snapshots, "config_drafts": drafts},
                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"盤點結果已寫入：{out}")
        print("草稿含 TODO，需人工補齊並實機驗證後，才能併入 ncl_openlab_rooms.json。")
        print("請自行關閉瀏覽器；結束。")
        # Leave the browser to the user, exactly like the booking tool.


def main():
    parser = argparse.ArgumentParser(description="國圖房型唯讀盤點與流程分類")
    parser.add_argument("--report-dir", default="ncl_reports")
    args = parser.parse_args()
    asyncio.run(run(args.report_dir))


if __name__ == "__main__":
    main()
