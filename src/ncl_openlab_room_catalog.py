# -*- coding: utf-8 -*-
"""Official OPEN LAB space/equipment catalog; no booking-site side effects.

Source: NCL multimedia overview (2026-11-04). These are *space categories*,
NOT live vacancy counts or evidence of an authenticated reservation contract.
Only P03 and music have passed room/slot DOM selection tests on a real browser.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RoomSpec:
    title: str
    channel: str  # "online" | "onsite_only"
    slot_profile: str  # "three_hour" | "hourly" | "unverified" | "onsite"
    automation: str  # "verified" | "needs_live_dom" | "onsite_only"


ROOM_CATALOG = {
    "discussion": RoomSpec("討論室", "online", "three_hour", "needs_live_dom"),
    "practice": RoomSpec("團練室", "online", "three_hour", "needs_live_dom"),
    "camera": RoomSpec("星際直播攝影棚", "online", "three_hour", "needs_live_dom"),
    "family": RoomSpec("親子直播室", "online", "three_hour", "needs_live_dom"),
    "music": RoomSpec("音樂創作室（3 小時）", "online", "three_hour", "verified"),
    "p03": RoomSpec("P03 個人直播室（1 小時）", "online", "hourly", "verified"),
    "sewing": RoomSpec("創藝手作坊縫紉機", "online", "unverified", "needs_live_dom"),
    "anime_pc": RoomSpec("動漫創作坊電腦", "online", "unverified", "needs_live_dom"),
    "thunder": RoomSpec("雷神工作室", "online", "unverified", "needs_live_dom"),
    "scan_pc": RoomSpec("影印掃描用電腦", "online", "unverified", "needs_live_dom"),
    "craft_pc": RoomSpec("創藝手作坊電腦", "online", "unverified", "needs_live_dom"),
    "digital_pc": RoomSpec("數位科技實作區電腦", "online", "unverified", "needs_live_dom"),
    "av_onsite": RoomSpec("影音欣賞區（僅限現場）", "onsite_only", "onsite", "onsite_only"),
    "language_onsite": RoomSpec("語言學習區（僅限現場）", "onsite_only", "onsite", "onsite_only"),
}

ROOM_CHOICES = {key: spec.title for key, spec in ROOM_CATALOG.items()}
ROOM_GROUPS = (
    ("已驗證可自動預約", ("music", "p03")),
    ("可線上預約・尚待實機辨識", tuple(
        key for key, spec in ROOM_CATALOG.items()
        if spec.automation == "needs_live_dom")),
    ("官網限定現場借用", ("av_onsite", "language_onsite")),
)

OFFICIAL_OVERVIEW_URL = (
    "https://spms.ncl.edu.tw/NLT/co/multimedia.jsp?page=media"
)


def room_status(room):
    try:
        return ROOM_CATALOG[room].automation
    except KeyError as exc:
        raise ValueError("不支援的空間") from exc


def room_notice(room):
    status = room_status(room)
    if status == "verified":
        return "已完成實機選取驗證；預約仍須官方回覆確認"
    if status == "onsite_only":
        return "官網標示僅限現場借用，程式禁止線上自動預約"
    return "官網列為可線上借用；尚待房間編號、時段及 DOM 實機驗證，禁止自動送出"
