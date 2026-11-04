# FROZEN GOLDEN COPY of src/ncl_openlab_autobook.py at commit 4d0da47.
# Used only by tests/test_ncl_openlab_legacy_parity.py to prove the data-driven
# engine behaves identically to the verified P03 implementation. DO NOT EDIT.
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


# Conservative minimum cadence for time-sensitive, bounded release checks.
PRE_REFRESH_SECONDS = 10
RETRY_INTERVAL_SECONDS = 3
RETRY_WINDOW_SECONDS = 90
RETRYABLE_BEFORE_SUBMIT = frozenset({
    "BLOCKED_DATE_NOT_UNIQUE", "BLOCKED_DATE_DISABLED",
    "BLOCKED_ROOM_NOT_UNIQUE", "NO_BOOKABLE_UI_SLOT",
})


def parse_p03_priorities(raw):
    """Ordered one-hour P03 alternatives; only one reservation is submitted."""
    values = tuple(v.strip() for v in raw.split(",")) if isinstance(raw, str) else ()
    if (not values or len(values) > len(P03_SLOTS) or
            len(values) != len(set(values)) or
            any(v not in P03_SLOTS for v in values)):
        raise ValueError("P03 時段必須是不重複的 09:00-10:00 至 19:00-20:00 整點一小時")
    return values


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
  const mode = __ROOM_MODE__;
  const visible = (el) => {
    const b = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return b.width > 0 && b.height > 0 && style.display !== "none" &&
      style.visibility !== "hidden";
  };
  if (location.hostname !== "spms.ncl.edu.tw") return "WRONG_HOST";
  if (document.querySelectorAll(".date-box").length > 0) return "GRID_READY";
  // Live NCL flow: the multimedia status overview is NOT the booking date grid.
  // Clicking the exact room category opens /NLT/co/media_discussion.jsp (7 dates).
  if (location.pathname === "/NLT/co/multimedia.jsp") {
    const roomName = mode === "p03" ? "個人直播室" : "音樂創作室";
    const labels = Array.from(document.querySelectorAll(".lab-item .lab-name[data-zh]"))
      .filter(el => visible(el) && el.getAttribute("data-zh") === roomName);
    if (labels.length !== 1) return "STATUS_ROOM_NOT_UNIQUE";
    const tile = labels[0].closest(".lab-item");
    if (!tile || !visible(tile) || tile.classList.contains("disabled") ||
        tile.classList.contains("unavailable") ||
        tile.getAttribute("aria-disabled") === "true")
      return "STATUS_ROOM_NOT_ACTIONABLE";
    tile.click();
    return "STATUS_ROOM_OPENED";
  }
  const agrees = Array.from(document.querySelectorAll("button#agree-btn.button.agree"))
    .filter(visible);
  if (agrees.length === 1) {
    if (!action) return "AGREEMENT_REQUIRED";
    if (String(agrees[0].innerText || "").replace(/\s+/g, "") !== "同意Agree")
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


async def ensure_date_grid(tab, *, accept_terms=False, mode="music"):
    """Navigate visible site UI only, without inventing consent or retrying submit."""
    if mode not in ROOM_MODES:
        return "INVALID_ROOM_MODE"
    if not await at_official_host(tab):
        return "WRONG_HOST"
    script = (ENTRY_JS
              .replace("__ALLOW_AGREE__", "true" if accept_terms else "false")
              .replace("__ROOM_MODE__", json.dumps(mode)))
    code = "ENTRY_NOT_FOUND_OR_AMBIGUOUS"
    for _ in range(12):
        code = await tab.evaluate(script)
        if code == "GRID_READY":
            return code
        if code not in ("MULTIMEDIA_OPENED", "AGREEMENT_CLICKED", "STATUS_ROOM_OPENED"):
            return code
        await asyncio.sleep(0.25)
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


# Diagnostic observations only: never intercept or send the booking request.
SUBMIT_PROBE_ARM_JS = r"""(() => {
  const b = document.querySelector("button#gobook.submit-circle-button");
  if (!b) return "NO_BUTTON";
  if (window.__nclSubmitProbe) return "ALREADY_ARMED";
  const p = window.__nclSubmitProbe = {click: false, trusted: null, ajax: false};
  b.addEventListener("click", e => {
    p.click = true;
    p.trusted = e.isTrusted === true;
  }, {capture: true, once: true});
  if (window.jQuery) {
    window.jQuery(document).on("ajaxSend.nclSubmitProbe", (_e, _xhr, settings) => {
      if (/step2_media[.]jsp(?:[?#]|$)/.test(String(settings.url || "")))
        p.ajax = true;
    });
  }
  return "ARMED";
})()"""

SUBMIT_PROBE_READ_JS = r"""(() => {
  const p = window.__nclSubmitProbe;
  return p ? {click: !!p.click, trusted: p.trusted, ajax: !!p.ajax} : null;
})()"""


async def submit_once_with_pointer(tab, day, slot, mode="music", attempts=8):
    """One real keyboard activation on the verified #gobook. Never retry submit.

    Zendriver Element.click runs JS el.click(), which did not book on NCL.
    Zendriver's native SpecialKeys.SPACE dispatches keydown+keyup on a focused
    button. This is a single distinct activation method, not a fallback click.
    Diagnostic observers only capture boolean click/AJAX signals, no PII.
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
                element = await tab.select("button#gobook.submit-circle-button", timeout=1)
                if element is None:
                    return "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY"
                if await tab.evaluate(SUBMIT_PROBE_ARM_JS) != "ARMED":
                    return "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY"
                from zendriver.core.keys import SpecialKeys
                await element.send_keys(SpecialKeys.SPACE)
            except Exception:
                # Even a timeout may occur after the booking was accepted.
                return "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY"
            print("submit method: ZENDRIVER_KEYBOARD_SPACE")
            try:
                probe = await tab.evaluate(SUBMIT_PROBE_READ_JS)
                if isinstance(probe, dict):
                    print("submit observation: click="
                          + str(bool(probe.get("click"))).lower()
                          + " trusted=" + str(probe.get("trusted")).lower()
                          + " ajax=" + str(bool(probe.get("ajax"))).lower())
            except Exception:
                pass  # A confirmed navigation can remove the probe; do not retry.
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


async def book_one_target(tab, day, priorities, *, auto_submit, mode="music", fast_probe=False):
    """One booking only. Never attempt another when this result is uncertain."""
    # Choose date and room once; stop on any ambiguous or disabled selector.
    for phase in ("date", "room"):
        code = await attempt_stage(tab, phase, day, priorities[0],
                                   attempts=2 if fast_probe else 8, mode=mode)
        print(f"{phase}: {code}")
        if code not in ("CLICKED", "ALREADY_SELECTED"):
            return "BLOCKED_" + code

    chosen_slot = None
    for slot in priorities:
        code = await attempt_stage(tab, "slot", day, slot,
                                   attempts=2 if fast_probe else 8, mode=mode)
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

    # The next button starts a navigation. An early click can reach the newly
    # painted #gobook before the site's click handler is attached. Wait for
    # the finished document and its required validation functions, then allow
    # a short fixed initialization gap. No polling/refresh of the site itself.
    checkout_ready_js = (
        'document.readyState === "complete" && '
        'document.querySelectorAll("button#gobook.submit-circle-button").length === 1 && '
        'typeof window.jQuery === "function" && '
        'typeof window.validateEmail === "function"'
    )
    for _ in range(20):
        if await tab.evaluate(checkout_ready_js) is True:
            break
        await asyncio.sleep(0.15)
    else:
        return "BLOCKED_CHECKOUT_NOT_READY"
    await asyncio.sleep(1.0)

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


async def refresh_booking_grid(tab, *, mode, accept_terms):
    """One official-page refresh; never submit anything or bypass terms."""
    await tab.reload(ignore_cache=False)
    await tab.wait_for_ready_state(until="interactive", timeout=10)
    return await ensure_date_grid(tab, accept_terms=accept_terms, mode=mode)


async def wait_until_release(tab, day, *, mode, accept_terms,
                             pre_refresh_seconds=PRE_REFRESH_SECONDS):
    """T-10 warmup once, then a mandatory T=00:00 release refresh."""
    remaining = seconds_until_release(day)
    if not 0 <= remaining <= 900:
        return "RELEASE_OUTSIDE_15_MINUTE_WINDOW"
    if pre_refresh_seconds and remaining >= pre_refresh_seconds:
        await asyncio.sleep(max(0, remaining - pre_refresh_seconds))
        if seconds_until_release(day) > 0:
            print("開放前 10 秒預刷新一次（不嘗試預約）。")
            status = await refresh_booking_grid(
                tab, mode=mode, accept_terms=accept_terms)
            if status != "GRID_READY":
                return "PRE_REFRESH_BLOCKED_" + status
    elif pre_refresh_seconds:
        print("不足 10 秒，略過預刷新，保留準點正式刷新。")

    remaining = seconds_until_release(day)
    if remaining > 0:
        await asyncio.sleep(remaining)
    print("台北時間 00:00：正式刷新，檢查日期及時段。")
    status = await refresh_booking_grid(tab, mode=mode, accept_terms=accept_terms)
    return status if status == "GRID_READY" else "RELEASE_REFRESH_BLOCKED_" + status


async def book_with_bounded_retries(
        tab, day, priorities, *, auto_submit, mode, accept_terms,
        retry_interval=RETRY_INTERVAL_SECONDS, retry_window=RETRY_WINDOW_SECONDS):
    """Retry only BEFORE reaching checkout; never repeat a final reservation.

    Poll cadence counts only page refreshes; no rapid background API calls.
    All stop codes after choosing a slot/going to checkout are terminal.
    """
    if not (3 <= retry_interval <= 30 and 0 <= retry_window <= 180):
        return "INVALID_RETRY_LIMITS"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + retry_window
    attempt = 0
    while True:
        attempt += 1
        outcome = await book_one_target(
            tab, day, priorities, auto_submit=auto_submit,
            mode=mode, fast_probe=True)
        if outcome not in RETRYABLE_BEFORE_SUBMIT:
            return outcome
        now = loop.time()
        if now + retry_interval > deadline:
            return "RELEASE_WINDOW_EXHAUSTED_" + outcome
        print(f"第 {attempt} 次：新日期或指定時段尚未可預約，"
              f"{retry_interval} 秒後重新整理。")
        await asyncio.sleep(retry_interval)
        status = await refresh_booking_grid(tab, mode=mode, accept_terms=accept_terms)
        if status != "GRID_READY":
            return "RETRY_ENTRY_BLOCKED_" + status


async def wait_until_browser_manually_closed(browser, *, interval=1.0):
    """Keep result page alive without requesting Enter or closing Chrome.

    Only monitor the locally controlled browser via DevTools; no website
    refresh, booking requests, or new UI actions are made after completion.
    Chromium can keep its parent process running after the last visible
    window closes, so also look for remaining page targets.
    """
    no_page_checks = 0
    while True:
        if browser.stopped:
            return
        try:
            # Zendriver's target-list call only queries the browser itself.
            targets = await browser._get_targets()
            if any(getattr(target, "type_", None) == "page"
                   for target in targets):
                no_page_checks = 0
            else:
                no_page_checks += 1
                if no_page_checks >= 3:
                    return
        except Exception:
            # Closing the browser can tear down CDP before the OS process
            # exits. A lost DevTools connection is therefore terminal.
            connection = getattr(browser, "connection", None)
            if browser.stopped or (
                    connection is not None and connection.closed):
                return
        await asyncio.sleep(interval)


async def autobook(day, priorities, *, auto_submit, now_mode=False,
                   mode="music", accept_terms=False, reserve_two=False,
                   retry_interval=RETRY_INTERVAL_SECONDS,
                   retry_window=RETRY_WINDOW_SECONDS):
    import zendriver as uc

    browser = await uc.start(headless=False)
    try:
        tab = await browser.get(NCL_URL)
        print("在此瀏覽器手動登入並開啟多媒體創意實驗中心的日期選擇畫面。")
        await asyncio.to_thread(input, "登入及進入頁面後按 Enter 啟動單次自動預約：")
        status = await ensure_date_grid(tab, accept_terms=accept_terms, mode=mode)
        if status == "AGREEMENT_REQUIRED":
            print("請親自閱讀並點選「同意 Agree」，返回日期頁後再按 Enter。")
            await asyncio.to_thread(input, "已同意並進入日期頁後按 Enter：")
            status = await ensure_date_grid(tab, accept_terms=False, mode=mode)
        if status != "GRID_READY":
            raise RuntimeError("DATE_GRID_NOT_READY_" + str(status))
        if not now_mode:
            status = await wait_until_release(
                tab, day, mode=mode, accept_terms=accept_terms)
            if status != "GRID_READY":
                return status

        if reserve_two:
            # Sequential 2 bookings, not a polling loop. Do not move on until
            # the previous submission is verified on the real success screen.
            if mode not in ROOM_MODES or len(priorities) != 2 or not auto_submit:
                return "INVALID_TWO_BOOKING_CONFIGURATION"
            for index, slot in enumerate(priorities):
                if index > 0:
                    tab = await tab.get(NCL_URL)
                    status = await ensure_date_grid(tab, accept_terms=accept_terms, mode=mode)
                    if status != "GRID_READY":
                        return "SECOND_ENTRY_BLOCKED_" + str(status)
                outcome = (await book_one_target(
                    tab, day, (slot,), auto_submit=True, mode=mode)
                    if now_mode else await book_with_bounded_retries(
                        tab, day, (slot,), auto_submit=True, mode=mode,
                        accept_terms=accept_terms,
                        retry_interval=retry_interval,
                        retry_window=retry_window))
                print(f"booking {index+1}/2 {slot}: {outcome}")
                if outcome != "SUCCESS_PAGE_MATCHED":
                    return ("FIRST_UNVERIFIED_SECOND_NOT_ATTEMPTED_"
                            if index == 0 else "SECOND_NOT_CONFIRMED_") + outcome
            return "TWO_BOOKINGS_CONFIRMED"
        if now_mode:
            return await book_one_target(tab, day, priorities,
                                         auto_submit=auto_submit, mode=mode)
        return await book_with_bounded_retries(
            tab, day, priorities, auto_submit=auto_submit, mode=mode,
            accept_terms=accept_terms,
            retry_interval=retry_interval, retry_window=retry_window)
    finally:
        # The actual reservation result stays visible for user inspection.
        # Only the user closes Chrome. Do not call browser.stop() or ask for
        # Enter (which previously ended the controller and closed Chromium).
        print("預約流程已結束；結果頁保留。請自行關閉瀏覽器，無需按 Enter。")
        await wait_until_browser_manually_closed(browser)


def main():
    parser = argparse.ArgumentParser(description="國圖音樂創作室／P03 單次自動預約")
    parser.add_argument("--date", required=True, type=date.fromisoformat,
                        help="目標日期 YYYY-MM-DD（必填）")
    parser.add_argument("--room", choices=ROOM_MODES, default="music",
                        help="music 音樂創作室（預設）或 p03 個人直播室測試")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--slots", default=None,
                        help="依優先順序指定時段，例如 13:00-16:00,09:00-12:00；P03 可指定一小時備選")
    target.add_argument("--slot", default=None, help="P03 唯一的一小時測試時段")
    parser.add_argument("--auto-submit", action="store_true",
                        help="明確允許程式在核對日期、房間、時段後點一次最終「預約」")
    parser.add_argument("--now", action="store_true",
                        help="立刻執行，不等預設的 7 日前台北 00:00")
    parser.add_argument("--accept-terms", action="store_true",
                        help="本人已閱讀同意 OPEN LAB 條款，允許在入口點一次「同意 Agree」")
    parser.add_argument("--reserve-two", action="store_true",
                        help="複選兩個時段依序預約兩次（music 或 P03），前一筆未確認成功就停止")
    parser.add_argument("--retry-interval", type=int, default=RETRY_INTERVAL_SECONDS,
                        help="午夜後未開放時刷新間隔（3–30秒，預設3秒）")
    parser.add_argument("--retry-window", type=int, default=RETRY_WINDOW_SECONDS,
                        help="午夜後最多重試秒數（0–180秒，預設90秒）")
    args = parser.parse_args()
    if not (3 <= args.retry_interval <= 30 and 0 <= args.retry_window <= 180):
        parser.error("重試間隔須為3–30秒，重試時間須為0–180秒")
    if args.room == "p03":
        if args.slot is None and args.slots is None:
            parser.error("P03 須指定 --slot 或 --slots（整點一小時）")
        try:
            priorities = ((args.slot,) if args.slot is not None
                          else parse_p03_priorities(args.slots))
        except ValueError as exc:
            parser.error(str(exc))
        if any(v not in P03_SLOTS for v in priorities):
            parser.error("P03 必須指定一小時時段")
    else:
        if args.slot is not None:
            parser.error("音樂創作室請用 --slots 指定三小時時段")
        try:
            priorities = parse_slot_priority(args.slots)
        except ValueError as exc:
            parser.error(str(exc))
    if args.reserve_two:
        if len(priorities) != 2:
            parser.error("--reserve-two 必須指定兩個不同的合法時段（music 或 P03）")
        if not args.auto_submit:
            parser.error("--reserve-two 需要明確指定 --auto-submit")
        print("雙時段模式：每天最多兩段（含已有預約）；第一筆未確認成功不執行第二筆。")
    room_name = ROOM if args.room == "music" else "個人直播室 P03"
    print(f"目標：{args.date.isoformat()}｜{room_name}｜優先序：{', '.join(priorities)}")
    print("注意：不繞驗證碼、不存帳密、不刷站；只會在此登入階段後操作。")
    if not args.auto_submit:
        print("未指定 --auto-submit，程式只會走到最後確認頁。")
    status = asyncio.run(autobook(args.date, priorities,
                                  auto_submit=args.auto_submit,
                                  now_mode=args.now, mode=args.room,
                                  accept_terms=args.accept_terms,
                                  reserve_two=args.reserve_two,
                                  retry_interval=args.retry_interval,
                                  retry_window=args.retry_window))
    print(json.dumps({"result": status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
