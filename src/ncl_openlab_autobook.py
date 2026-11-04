#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot, opt-in NCL room booking through the visible browser UI.

Generic, data-driven engine: every per-room difference (tile matcher, slot
list, slot-tile behaviour, confirmation-page wording) lives in
``ncl_openlab_rooms.json``. Music room and P03 are the first two profiles.

Manual login required. One target date, one room, at most one final submit.
No API replay, CAPTCHA solving, rapid page refresh or continuous polling.
"""
import argparse
import asyncio
import contextvars
import json
import os
import sys
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from ncl_openlab_auth import (
    LOGIN_TIMEOUT, RECOVER_MARGIN, TERMS_JS, Authenticator, TermsConsent, _script,
    load_site, probe_state, standby_guard, validate_terms,
)
from ncl_openlab_browser import cleanup_browser, start_browser
from ncl_openlab_control import (
    PROJECT_ROOT, CancelWatcher, LOCK_PATH, RunLock, RunLockBusy, encode_event,
)
from ncl_openlab_credentials import CredentialStore
from ncl_openlab_guard import NCL_HOST
from ncl_openlab_probe import NCL_URL, TAIPEI_TZ
from ncl_openlab_rooms import get_registry
from ncl_openlab_schedule import (
    LATE_GRACE_SECONDS, MAX_CUSTOM_WAIT_SECONDS, ScheduleCancelled, ScheduleMissed,
    SystemClock, Timeline, check_run_at, format_countdown, measure_clock_offset,
    parse_run_at, release_run_at,
)

# Fixed, exact labels and site selectors. Never click unknown elements.
PHASES = ("date", "room", "slot", "next", "submit", "success")
_REGISTRY = get_registry()
ROOM_MODES = _REGISTRY.keys
DEFAULT_ROOM = "music"
# Kept for compatibility with the picker GUI and existing callers.
P03_SLOTS = _REGISTRY.room("p03").slots
_TRACE = contextvars.ContextVar("ncl_trace", default=None)
_MACHINE = contextvars.ContextVar("ncl_machine", default=False)
_TERMS = contextvars.ContextVar("ncl_terms", default=None)
TERMS_PATH = PROJECT_ROOT / "ncl_reports" / "ncl_terms_consent.json"


def _emit(state, **fields):
    """State line for the GUI supervisor. Silent unless --machine-status is on."""
    if _MACHINE.get():
        # Leading newline: input() prompts have none, which would glue this onto them.
        print("\n" + encode_event(state, **fields), flush=True)


def _note(label, code):
    """Print one stage result and record it for the optional run report."""
    print(f"{label}: {code}")
    trace = _TRACE.get()
    if trace is not None:
        trace.append((label, str(code)))
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
  // Room identity comes from the profile (ncl_openlab_rooms.json), never from
  // fuzzy guessing: exactly one visible tile must match.
  const roomMatches = (text) => task.profile.tileKind === "regex"
    ? new RegExp(task.profile.tileValue).test(text)
    : text.includes(task.profile.tileValue);
  const roomTile = () => exactOne(from(".space-box1")
    .filter(el => roomMatches(cleanText(el))));
  const slotTile = () => exactOne(from(task.profile.slotSelector)
    .filter(el => el.getAttribute("data-param1") === task.slot));
  // Flows differ: P03-style hourly tiles gain 'book' once selected (observed
  // live HTML); block tiles use 'selected'. The profile's flow says which.
  const chosen = (el, kind) => el && (el.classList.contains("selected") ||
    (task.profile.bookMarksSelected && kind === "slot" && el.classList.contains("book")));
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
    // Hourly tiles can be chosen before they gain 'book'. Block tiles keep the
    // positive 'book' requirement.
    if (task.profile.slotRequiresBook && !tile.classList.contains("book"))
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
  const matchingRoomSummary = (display) => {
    const squeezed = display.replace(/\s+/g, "");
    return task.profile.summaryTextAll.every(
        t => squeezed.includes(String(t).replace(/\s+/g, ""))) &&
      task.profile.summaryRegexAll.every(p => new RegExp(p).test(display));
  };
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


def room_profile(mode):
    """Profile for a configured room key; unknown keys fail closed."""
    if mode not in ROOM_MODES:
        raise ValueError("invalid phase or room mode")
    return _REGISTRY.room(mode)


def action_script(phase, day, slot, mode="music"):
    if phase not in PHASES or mode not in ROOM_MODES:
        raise ValueError("invalid phase or room mode")
    profile = room_profile(mode)
    if (not isinstance(day, date) or isinstance(day, datetime)
            or slot not in profile.slots):
        raise ValueError("invalid slot for requested room")
    data = {"phase": phase, "shortDate": day.strftime("%m/%d"),
            "fullDate": day.strftime("%Y/%m/%d"),
            "isoDate": day.isoformat(), "room": profile.entry_label,
            "slot": slot, "mode": mode, "profile": profile.task_profile()}
    return ACTION_JS.replace("__TASK__", json.dumps(data, ensure_ascii=False))


# Conservative minimum cadence for time-sensitive, bounded release checks.
PRE_REFRESH_SECONDS = 10
RETRY_INTERVAL_SECONDS = 3
RETRY_WINDOW_SECONDS = 90
RETRYABLE_BEFORE_SUBMIT = frozenset({
    "BLOCKED_DATE_NOT_UNIQUE", "BLOCKED_DATE_DISABLED",
    "BLOCKED_ROOM_NOT_UNIQUE", "NO_BOOKABLE_UI_SLOT",
})


def parse_room_priorities(mode, raw):
    """Ordered slot alternatives for any configured room (first = preferred)."""
    profile = room_profile(mode)
    if raw is None and profile.default_all_slots:
        return profile.slots
    values = tuple(v.strip() for v in raw.split(",")) if isinstance(raw, str) else ()
    if (not values or len(values) > len(profile.slots) or
            len(values) != len(set(values)) or
            any(v not in profile.slots for v in values)):
        raise ValueError(f"{profile.label} 時段必須是不重複的合法時段："
                         + ", ".join(profile.slots))
    return values


def parse_p03_priorities(raw):
    """Ordered one-hour P03 alternatives; only one reservation is submitted."""
    return parse_room_priorities("p03", raw)


def release_time(day):
    # Seven days before target. 00:00 is a user-observed timing assumption,
    # not a confirmed NCL time-of-day guarantee. It is only the DEFAULT start;
    # any other start time goes through --run-at and the same Timeline.
    return release_run_at(day)


def seconds_until_release(day, now=None):
    t = now or datetime.now(TAIPEI_TZ)
    if t.tzinfo is None:
        raise ValueError("now must have timezone")
    return (release_time(day) - t.astimezone(TAIPEI_TZ)).total_seconds()


# One-shot lobby navigation from actual NCL entry markup. Consent is opt-in.
ENTRY_JS = r"""(() => {
  const action = __ALLOW_AGREE__;
  const roomName = __ROOM_ENTRY_LABEL__;
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
    // Rooms whose status-page category is unknown must be opened by hand.
    if (roomName === null) return "ENTRY_MANUAL_REQUIRED";
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


def entry_script(mode, accept_terms=False):
    """Lobby-navigation script for a configured room (exact label, no guessing)."""
    return (ENTRY_JS
            .replace("__ALLOW_AGREE__", "true" if accept_terms else "false")
            .replace("__ROOM_ENTRY_LABEL__",
                     json.dumps(room_profile(mode).entry_label, ensure_ascii=False)))


async def ensure_date_grid(tab, *, accept_terms=False, mode="music", terms=None):
    """Navigate visible site UI only, without inventing consent or retrying submit.

    With a TermsConsent store the rules dialog is auto-accepted ONLY when its exact
    version (content hash) was agreed to by the user before; a new or changed
    version is left for the user to read and accept, then remembered.
    """
    if mode not in ROOM_MODES:
        return "INVALID_ROOM_MODE"
    if not await at_official_host(tab):
        return "WRONG_HOST"
    terms = terms if terms is not None else _TERMS.get()
    allow = accept_terms
    if terms is not None:
        info = validate_terms(await tab.evaluate(
            _script(TERMS_JS, MARKER=load_site()["terms"]["marker_text"])))
        if info and info["present"]:
            terms.pending = info["hash"]
            allow = bool(accept_terms and terms.is_consented(info["hash"]))
        elif info is None:
            allow = False        # cannot read the dialog: never auto-accept blind
    script = entry_script(mode, allow)
    code = "ENTRY_NOT_FOUND_OR_AMBIGUOUS"
    for _ in range(12):
        code = await tab.evaluate(script)
        if code == "GRID_READY":
            if terms is not None and terms.pending:
                terms.record(terms.pending)   # the user (or their consented version) agreed
                terms.pending = None
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
        _note(phase, code)
        if code not in ("CLICKED", "ALREADY_SELECTED"):
            return "BLOCKED_" + code

    chosen_slot = None
    for slot in priorities:
        code = await attempt_stage(tab, "slot", day, slot,
                                   attempts=2 if fast_probe else 8, mode=mode)
        _note(f"slot {slot}", code)
        if code in ("CLICKED", "ALREADY_SELECTED"):
            chosen_slot = slot
            break
        if code not in ("SLOT_DISABLED", "SLOT_NOT_BOOK_CLASS", "SLOT_NOT_UNIQUE"):
            return "BLOCKED_" + code
    if chosen_slot is None:
        return "NO_BOOKABLE_UI_SLOT"

    code = await attempt_stage(tab, "next", day, chosen_slot, attempts=8, mode=mode)
    _note("next", code)
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
    _note("submit", code)
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
    try:
        await tab.reload(ignore_cache=False)
        await tab.wait_for_ready_state(until="interactive", timeout=10)
    except Exception as exc:
        # Network loss or a dead tab: report it, never turn it into a submit.
        return "REFRESH_FAILED_" + type(exc).__name__
    status = await ensure_date_grid(tab, accept_terms=accept_terms, mode=mode)
    if status != "GRID_READY" and await probe_state(tab) in ("LOGIN_REQUIRED", "OFF_SITE"):
        return "SESSION_EXPIRED"   # the site sent us to its login: nothing may be booked
    return status


async def wait_until_release(tab, day, *, mode, accept_terms,
                             pre_refresh_seconds=PRE_REFRESH_SECONDS,
                             timeline=None, max_wait_seconds=900):
    """T-10 warm-up once, then a mandatory refresh exactly at the start time.

    One algorithm for every start time. Without a ``timeline`` the start time is
    the default release moment (target - 7 days, 00:00) and the wait window is
    15 minutes; with a Timeline (--run-at) the same steps run against that time.
    """
    remaining_now = timeline.remaining if timeline else (lambda: seconds_until_release(day))
    pause = timeline.sleep if timeline else asyncio.sleep
    try:
        remaining = remaining_now()
        if timeline is None:
            if not 0 <= remaining <= max_wait_seconds:
                return "RELEASE_OUTSIDE_15_MINUTE_WINDOW"
        elif remaining < -timeline.grace:
            return "RUN_AT_MISSED"
        elif remaining > max_wait_seconds:
            return "RUN_AT_TOO_FAR"
        if pre_refresh_seconds and remaining >= pre_refresh_seconds:
            await pause(max(0, remaining - pre_refresh_seconds))
            if remaining_now() > 0:
                print("預定時間前 10 秒預刷新一次（不嘗試預約）。")
                status = await refresh_booking_grid(
                    tab, mode=mode, accept_terms=accept_terms)
                if status != "GRID_READY":
                    return "PRE_REFRESH_BLOCKED_" + status
        elif pre_refresh_seconds:
            print("不足 10 秒，略過預刷新，保留準點正式刷新。")

        remaining = remaining_now()
        if remaining > 0:
            await pause(remaining)
    except ScheduleMissed:
        return "RUN_AT_MISSED"
    except ScheduleCancelled:
        return "CANCELLED_BEFORE_START"
    print("預定時間到：正式刷新，檢查日期及時段。")
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


async def run_dry_run(tab, day, priorities, mode):
    """Read-only diagnostics of the current page. No reservation control is touched."""
    from ncl_openlab_diag import diagnose, diagnose_script

    snapshots = {}
    for slot in priorities:
        raw = await tab.evaluate(diagnose_script(day, slot, mode))
        snapshots[slot] = diagnose(raw, mode)
        _note(f"diagnose {slot}", ",".join(snapshots[slot]["findings"]))
    return "DRY_RUN_COMPLETE", snapshots


def preflight(day, priorities, *, mode, auto_submit, dry_run, reserve_two):
    """Re-verify everything the engine is about to act on. None means all good."""
    try:
        room_profile(mode)
        for slot in priorities:
            action_script("slot", day, slot, mode)
    except ValueError:
        return "PREFLIGHT_TARGET_INVALID"
    if len(set(priorities)) != len(priorities) or not 1 <= len(priorities) <= len(
            room_profile(mode).slots):
        return "PREFLIGHT_TARGET_INVALID"
    if reserve_two and (len(priorities) != 2 or not auto_submit):
        return "INVALID_TWO_BOOKING_CONFIGURATION"
    if dry_run and auto_submit:
        return "INVALID_DRY_RUN_WITH_AUTO_SUBMIT"
    return None


async def _enter_date_grid(tab, auth, *, mode, accept_terms, cancelled, deadline):
    """Auth mode: reach the date grid without a keyboard Enter. Waits for the user only
    where a human must act (rules not yet accepted, or an unverified lobby category)."""
    started, tries = auth.clock.now(), 0
    while True:
        status = await ensure_date_grid(tab, accept_terms=accept_terms, mode=mode)
        if status == "GRID_READY":
            return None
        if status in ("AGREEMENT_REQUIRED", "ENTRY_MANUAL_REQUIRED"):
            auth._set("AUTH_INTERACTION_REQUIRED", (
                "請在瀏覽器親自閱讀並按「同意」（此規範版本尚未同意過，或內容已更新）"
                if status == "AGREEMENT_REQUIRED" else
                "請在瀏覽器手動開啟此設備的日期頁（設備類別尚未實機確認）"))
            if cancelled():
                return "CANCELLED_BEFORE_START"
            now = auth.clock.now()
            if deadline is not None and now >= deadline:
                return "AUTH_NOT_COMPLETED_BEFORE_START"
            if (now - started).total_seconds() > auth.timeout:
                return "AUTH_NO_RESPONSE"
            await auth.clock.sleep(auth.poll)
            continue
        tries += 1
        if await probe_state(tab, auth.site) in ("LOGIN_REQUIRED", "OFF_SITE") and tries <= 2:
            code = await auth.ensure(deadline=deadline, reason="expired")
            if code:
                return code
            continue
        if tries >= 3:
            return "DATE_GRID_NOT_READY_" + str(status)
        await auth.clock.sleep(auth.poll)


async def _drive(tab, day, priorities, *, auto_submit, now_mode, mode,
                 accept_terms, reserve_two, retry_interval, retry_window,
                 dry_run, extras, run_at=None, clock=None, machine=False,
                 late_grace_seconds=LATE_GRACE_SECONDS, auth_check=False,
                 use_saved_login=False, login_timeout=LOGIN_TIMEOUT):
    """The booking state machine itself (shared by every room and start time)."""
    watcher = auth = None
    if auth_check:
        # Session check instead of a keyboard Enter: reuse a valid login, otherwise wait
        # for the user to type the picture CAPTCHA, and confirm from the real page state.
        watcher = CancelWatcher().start() if machine else None
        cancelled = watcher.is_set if watcher else (lambda: False)
        if run_at is None and not now_mode and not dry_run:
            run_at = release_time(day)    # the default start goes through the same Timeline
        auth = Authenticator(
            tab, clock=clock, cancelled=cancelled,
            confirmed=watcher.is_ready if watcher else None,
            emit=lambda state, detail: _emit("LOGIN", auth=state, detail=detail),
            credentials=(lambda: CredentialStore().load()) if use_saved_login else None,
            timeout=login_timeout)
        deadline = (run_at - timedelta(seconds=RECOVER_MARGIN)) if run_at else None
        _emit("LOGIN", auth="LOGIN_VERIFYING", detail="檢查登入狀態")
        code = await auth.ensure(deadline=deadline)
        if code:
            return code
        code = await _enter_date_grid(tab, auth, mode=mode, accept_terms=accept_terms,
                                      cancelled=cancelled, deadline=deadline)
        if code:
            return code
    else:
        _emit("LOGIN")
        print("在此瀏覽器手動登入並開啟多媒體創意實驗中心的日期選擇畫面。")
        answer = await asyncio.to_thread(input, "登入及進入頁面後按 Enter 啟動單次自動預約：")
        if str(answer).strip().upper() == "CANCEL":
            return "CANCELLED_BEFORE_START"
        status = await ensure_date_grid(tab, accept_terms=accept_terms, mode=mode)
        if status == "AGREEMENT_REQUIRED":
            print("請親自閱讀並點選「同意 Agree」，返回日期頁後再按 Enter。")
            answer = await asyncio.to_thread(input, "已同意並進入日期頁後按 Enter：")
            if str(answer).strip().upper() == "CANCEL":
                return "CANCELLED_BEFORE_START"
            status = await ensure_date_grid(tab, accept_terms=False, mode=mode)
        if status == "ENTRY_MANUAL_REQUIRED":
            raise RuntimeError("DATE_GRID_NOT_READY_ENTRY_MANUAL_REQUIRED")
        if status != "GRID_READY":
            raise RuntimeError("DATE_GRID_NOT_READY_" + str(status))
    problem = preflight(day, priorities, mode=mode, auto_submit=auto_submit,
                        dry_run=dry_run, reserve_two=reserve_two)
    if problem:
        return problem
    if dry_run:
        _emit("RUNNING")
        outcome, extras["diagnosis"] = await run_dry_run(tab, day, priorities, mode)
        return outcome
    if not now_mode:
        if watcher is None and machine:
            watcher = CancelWatcher().start()
        timeline = None
        if run_at is not None:
            timeline = Timeline(
                run_at, clock, grace=late_grace_seconds,
                cancelled=(watcher.is_set if watcher else None),
                on_event=lambda kind, detail: print(f"時間事件 {kind}: {detail}"))
            problem = check_run_at(run_at, timeline.clock.now(), day,
                                   max_wait_seconds=MAX_CUSTOM_WAIT_SECONDS,
                                   grace=late_grace_seconds)
            if problem:
                return problem
            print(f"待命：{run_at:%Y-%m-%d %H:%M:%S}（台北）開始預約，"
                  f"剩 {format_countdown(timeline.remaining())}。")
            _emit("STANDBY", run_at=run_at.isoformat(),
                  clock_offset=getattr(timeline.clock, "offset_seconds", 0.0))
        else:
            _emit("STANDBY", run_at=release_time(day).isoformat(), clock_offset=0.0)
        if auth is not None and timeline is not None:
            try:
                guard = await standby_guard(
                    auth, timeline,
                    real_check=lambda: refresh_booking_grid(
                        tab, mode=mode, accept_terms=accept_terms),
                    reenter=lambda: ensure_date_grid(tab, accept_terms=accept_terms, mode=mode))
            except ScheduleMissed:
                return "RUN_AT_MISSED"
            except ScheduleCancelled:
                return "CANCELLED_BEFORE_START"
            if guard:
                return guard
            _emit("STANDBY", run_at=run_at.isoformat(),
                  clock_offset=getattr(timeline.clock, "offset_seconds", 0.0))
        status = await wait_until_release(
            tab, day, mode=mode, accept_terms=accept_terms, timeline=timeline,
            max_wait_seconds=(MAX_CUSTOM_WAIT_SECONDS if timeline else 900))
        if status != "GRID_READY":
            return status
    _emit("RUNNING")

    if reserve_two:
        # Sequential 2 bookings, not a polling loop. Do not move on until
        # the previous submission is verified on the real success screen.
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


async def _write_run_report(tab, *, report_dir, screenshot, day, mode,
                            priorities, outcome, trace, flags, extras, schedule):
    """Best effort. A reporting problem must never alter or repeat a booking."""
    try:
        from ncl_openlab_diag import build_report, capture_screenshot, write_report
        from datetime import datetime as _dt

        stem = "ncl_run_" + _dt.now(TAIPEI_TZ).strftime("%Y%m%d_%H%M%S")
        shot = None
        if screenshot and tab is not None:
            shot = await capture_screenshot(tab, report_dir, stem)
        report = build_report(day=day, mode=mode, priorities=priorities,
                              outcome=outcome, trace=trace, flags=flags,
                              diagnosis=extras.get("diagnosis"), screenshot=shot,
                              schedule=schedule)
        path = write_report(report_dir, report, stem=stem)
        print(f"診斷報告已寫入：{path}")
    except Exception as exc:
        print("診斷報告寫入失敗：" + type(exc).__name__)


async def autobook(day, priorities, *, auto_submit, now_mode=False,
                   mode="music", accept_terms=False, reserve_two=False,
                   retry_interval=RETRY_INTERVAL_SECONDS,
                   retry_window=RETRY_WINDOW_SECONDS,
                   dry_run=False, report_dir=None, screenshot=False,
                   run_at=None, clock=None, machine=False, run_lock=None,
                   late_grace_seconds=LATE_GRACE_SECONDS, auth_check=False,
                   use_saved_login=False, login_timeout=LOGIN_TIMEOUT, terms=None):
    import zendriver as uc

    if dry_run and auto_submit:
        return "INVALID_DRY_RUN_WITH_AUTO_SUBMIT"
    machine_token = _MACHINE.set(bool(machine))
    terms_token = _TERMS.set(terms)
    _emit("LAUNCHING")
    browser = await start_browser(uc)
    trace, extras, tab = [], {}, None
    token = _TRACE.set(trace)
    outcome = "ABORTED_BEFORE_RESULT"
    try:
        tab = await browser.get(NCL_URL)
        outcome = await _drive(
            tab, day, priorities, auto_submit=auto_submit, now_mode=now_mode,
            mode=mode, accept_terms=accept_terms, reserve_two=reserve_two,
            retry_interval=retry_interval, retry_window=retry_window,
            dry_run=dry_run, extras=extras, run_at=run_at, clock=clock,
            machine=machine, late_grace_seconds=late_grace_seconds,
            auth_check=auth_check, use_saved_login=use_saved_login,
            login_timeout=login_timeout)
        return outcome
    except BaseException as exc:
        outcome = "EXCEPTION_" + type(exc).__name__
        raise
    finally:
        _TRACE.reset(token)
        # The booking is over: free the one-at-a-time lock, then tell the GUI.
        if run_lock is not None:
            run_lock.release()
        _emit("DONE", outcome=outcome)
        if report_dir:
            await _write_run_report(
                tab, report_dir=report_dir, screenshot=screenshot, day=day,
                mode=mode, priorities=priorities, outcome=outcome, trace=trace,
                flags={"auto_submit": auto_submit, "now": now_mode,
                       "reserve_two": reserve_two, "dry_run": dry_run},
                extras=extras,
                schedule={"run_at": run_at.isoformat() if run_at else None,
                          "clock_offset_seconds": getattr(clock, "offset_seconds", 0.0)})
        _MACHINE.reset(machine_token)
        _TERMS.reset(terms_token)
        if outcome == "CANCELLED_BEFORE_START":
            print("已取消排程，關閉瀏覽器。")
        else:
            # The actual reservation result stays visible for user inspection.
            # Only the user closes Chrome. Do not call browser.stop() or ask for
            # Enter (which previously ended the controller and closed Chromium).
            print("預約流程已結束；結果頁保留。請自行關閉瀏覽器，無需按 Enter。")
            await wait_until_browser_manually_closed(browser)
        # Window closed by the user (or cancelled): stop the lingering Chrome
        # process (macOS keeps it alive) and delete its throwaway profile.
        await cleanup_browser(browser)


def build_parser():
    parser = argparse.ArgumentParser(description="國圖多媒體創意實驗中心單次自動預約（多房型）")
    parser.add_argument("--date", required=True, type=date.fromisoformat,
                        help="目標日期 YYYY-MM-DD（必填）")
    parser.add_argument("--room", choices=ROOM_MODES, default=DEFAULT_ROOM,
                        help="房型代號，定義於 ncl_openlab_rooms.json；"
                             "music 音樂創作室（預設）、p03 個人直播室")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--slots", default=None,
                        help="依優先順序指定時段，例如 13:00-16:00,09:00-12:00；P03 可指定一小時備選")
    target.add_argument("--slot", default=None, help="P03 唯一的一小時測試時段")
    parser.add_argument("--auto-submit", action="store_true",
                        help="明確允許程式在核對日期、房間、時段後點一次最終「預約」")
    timing = parser.add_mutually_exclusive_group()
    timing.add_argument("--now", action="store_true",
                        help="立刻執行，不等預設的 7 日前台北 00:00")
    timing.add_argument("--run-at", default=None, metavar="ISO8601",
                        help="自訂開始預約時間（台北時間），例如 2026-11-05T00:00:00+08:00；"
                             "未含時區視為台北時間。未指定時維持目標日前 7 日 00:00 的預設")
    parser.add_argument("--clock-offset", type=float, default=0.0, metavar="SEC",
                        help="手動校正：網路時間減系統時間的秒數（±600 內）")
    parser.add_argument("--sync-clock", action="store_true",
                        help="啟動前以 NTP 量測系統時間誤差並自動校正排程（失敗不影響執行）")
    parser.add_argument("--accept-terms", action="store_true",
                        help="本人已閱讀同意 OPEN LAB 條款，允許在入口點一次「同意 Agree」")
    parser.add_argument("--reserve-two", action="store_true",
                        help="複選兩個時段依序預約兩次（music 或 P03），前一筆未確認成功就停止")
    parser.add_argument("--retry-interval", type=int, default=RETRY_INTERVAL_SECONDS,
                        help="午夜後未開放時刷新間隔（3–30秒，預設3秒）")
    parser.add_argument("--retry-window", type=int, default=RETRY_WINDOW_SECONDS,
                        help="午夜後最多重試秒數（0–180秒，預設90秒）")
    parser.add_argument("--dry-run", action="store_true",
                        help="唯讀診斷：登入後只檢查目前頁面的日期／房型／時段狀態，"
                             "不點任何預約控制項，不可與 --auto-submit 併用")
    parser.add_argument("--plan-only", action="store_true",
                        help="只印出解析後的計畫並結束，不開瀏覽器")
    parser.add_argument("--report-dir", default=None,
                        help="將去識別化診斷報告(JSON)寫到此資料夾；--dry-run 預設 ncl_reports")
    parser.add_argument("--screenshot", action="store_true",
                        help="結束時另存目前頁面截圖（可能含個人資料，僅存本機，需搭配報告）")
    parser.add_argument("--ack-room-unverified", action="store_true",
                        help="確認接受此房型尚未實機驗證的風險（新增房型設定要求時才需要）")
    parser.add_argument("--machine-status", action="store_true",
                        help="供前端使用：輸出 @@NCL 狀態行，並在待命時接受 stdin 的 CANCEL")
    parser.add_argument("--auth-check", action="store_true",
                        help="以登入狀態機取代「登入後按 Enter」：沿用有效登入，否則等你輸入驗證碼並自動確認；"
                             "待命期間監看登入狀態")
    parser.add_argument("--use-saved-login", action="store_true",
                        help="登入頁出現時，把系統金鑰庫中的帳密填入官方登入表單（驗證碼與登入鈕仍由你操作）；"
                             "需 --auth-check")
    parser.add_argument("--login-timeout-minutes", type=int, default=int(LOGIN_TIMEOUT // 60),
                        help="等待你完成登入／驗證碼的上限分鐘數（1–60，預設 10）")
    return parser


def resolve_priorities(parser, args):
    """Validate the slot arguments against the chosen room's profile."""
    profile = room_profile(args.room)
    if args.slot is not None and not profile.single_slot_option:
        parser.error(f"{profile.label}請用 --slots 指定時段")
    raw = args.slot if args.slot is not None else args.slots
    if raw is None and not profile.default_all_slots:
        parser.error(f"{profile.label} 須指定 --slot 或 --slots（"
                     + ", ".join(profile.slots[:1] + profile.slots[-1:]) + "）")
    try:
        return parse_room_priorities(args.room, raw)
    except ValueError as exc:
        parser.error(str(exc))


RUN_AT_MESSAGES = {
    "RUN_AT_ALREADY_PASSED": "自訂開始時間已經過了",
    "RUN_AT_TOO_FAR": "自訂開始時間超過 24 小時，請改在較近的時間啟動",
    "RUN_AT_AFTER_TARGET_DAY": "自訂開始時間晚於預約日，沒有意義",
    "RUN_AT_INVALID": "自訂開始時間無法解讀",
}


def resolve_schedule(parser, args):
    """(run_at, clock) from --run-at / --clock-offset / --sync-clock."""
    offset = args.clock_offset
    if args.sync_clock:
        if args.clock_offset:
            parser.error("--sync-clock 與 --clock-offset 擇一")
        measured, note = measure_clock_offset()
        print(note)
        offset = measured or 0.0
    try:
        clock = SystemClock(offset)
    except ValueError:
        parser.error("--clock-offset 必須在 ±600 秒內")
    run_at = None
    if args.run_at is not None:
        if args.dry_run:
            parser.error("--dry-run 不排程，請拿掉 --run-at")
        try:
            run_at = parse_run_at(args.run_at)
        except ValueError as exc:
            parser.error(str(exc))
        problem = check_run_at(run_at, clock.now(), args.date,
                               max_wait_seconds=MAX_CUSTOM_WAIT_SECONDS)
        if problem:
            parser.error(RUN_AT_MESSAGES[problem] + f"（{problem}）")
    return run_at, clock


class _TolerantStream:
    """stdout that survives a vanished GUI: a booking must never die on print()."""

    def __init__(self, inner):
        self._inner = inner

    def write(self, text):
        try:
            return self._inner.write(text)
        except (OSError, ValueError):
            return len(text)

    def flush(self):
        try:
            self._inner.flush()
        except (OSError, ValueError):
            pass

    def __getattr__(self, name):
        return getattr(self._inner, name)


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.machine_status:
        sys.stdout = _TolerantStream(sys.stdout)
    if not (3 <= args.retry_interval <= 30 and 0 <= args.retry_window <= 180):
        parser.error("重試間隔須為3–30秒，重試時間須為0–180秒")
    profile = room_profile(args.room)
    priorities = resolve_priorities(parser, args)
    if args.dry_run and args.auto_submit:
        parser.error("--dry-run 為唯讀診斷，不可與 --auto-submit 併用")
    if args.use_saved_login and not args.auth_check:
        parser.error("--use-saved-login 需要同時指定 --auth-check")
    if not 1 <= args.login_timeout_minutes <= 60:
        parser.error("--login-timeout-minutes 須為 1–60")
    if args.dry_run and args.reserve_two:
        parser.error("--dry-run 不可與 --reserve-two 併用")
    if args.screenshot and not (args.report_dir or args.dry_run):
        parser.error("--screenshot 需搭配 --report-dir 或 --dry-run")
    if args.auto_submit and profile.submit_requires_ack and not args.ack_room_unverified:
        parser.error(f"{profile.label} 尚未實機驗證，送出前須明確加上 --ack-room-unverified")
    run_at, clock = resolve_schedule(parser, args)
    if args.reserve_two:
        if len(priorities) != 2:
            parser.error("--reserve-two 必須指定兩個不同的合法時段（music 或 P03）")
        if not args.auto_submit:
            parser.error("--reserve-two 需要明確指定 --auto-submit")
        print("雙時段模式：每天最多兩段（含已有預約）；第一筆未確認成功不執行第二筆。")
    print(f"目標：{args.date.isoformat()}｜{profile.label}｜優先序：{', '.join(priorities)}")
    print("注意：不繞驗證碼、不存帳密、不刷站；只會在此登入階段後操作。")
    if profile.live != "LIVE_VERIFIED":
        print(f"提醒：{profile.label} 尚未實機驗證（NOT_VERIFIED）：{profile.live_notes}")
    if args.dry_run:
        print("唯讀診斷模式（--dry-run）：不會點選預約相關控制項，也不會送出。")
    elif not args.auto_submit:
        print("未指定 --auto-submit，程式只會走到最後確認頁。")
    if args.plan_only:
        start = ("now" if args.now else (run_at or release_time(args.date)).isoformat())
        print(json.dumps({"plan": {
            "room": args.room, "flow": profile.flow.name, "date": args.date.isoformat(),
            "slots": list(priorities), "auto_submit": args.auto_submit,
            "dry_run": args.dry_run, "now": args.now, "start_at": start,
            "custom_start": run_at is not None,
            "release_taipei": release_time(args.date).isoformat(),
            "clock_offset_seconds": clock.offset_seconds,
            "live_evidence": profile.live}}, ensure_ascii=False))
        return
    lock = RunLock(os.environ.get("NCL_LOCK_PATH") or LOCK_PATH)
    try:
        lock.acquire()
    except RunLockBusy as exc:
        parser.error(f"{exc}；同一時間只允許一個預約程序，避免重複送出")
    report_dir = args.report_dir or ("ncl_reports" if args.dry_run else None)
    try:
        status = asyncio.run(autobook(args.date, priorities,
                                      auto_submit=args.auto_submit,
                                      now_mode=args.now, mode=args.room,
                                      accept_terms=args.accept_terms,
                                      reserve_two=args.reserve_two,
                                      retry_interval=args.retry_interval,
                                      retry_window=args.retry_window,
                                      dry_run=args.dry_run, report_dir=report_dir,
                                      screenshot=args.screenshot, run_at=run_at,
                                      clock=clock, machine=args.machine_status,
                                      run_lock=lock, auth_check=args.auth_check,
                                      use_saved_login=args.use_saved_login,
                                      login_timeout=args.login_timeout_minutes * 60.0,
                                      terms=TermsConsent(os.environ.get("NCL_TERMS_PATH")
                                                         or TERMS_PATH)))
    finally:
        lock.release()
    print(json.dumps({"result": status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
