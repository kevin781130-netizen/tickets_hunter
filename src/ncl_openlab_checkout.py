# -*- coding: utf-8 -*-
"""Read-only NCL final reservation step inspector.

This module never clicks, submits, refreshes, reads form values, or requests
reservation APIs. A visible booking CTA is not a confirmed reservation.
"""
import json
from datetime import date, datetime

from ncl_openlab_guard import NCL_HOST, ROOM, VALID_SLOTS

CTA_LABELS = ("下一步", "預約", "確認預約", "送出預約", "完成預約")
SOURCE = "ncl_checkout_dom_v1"

CHECKOUT_JS = r"""(() => {
  const expected = __EXPECTED__;
  const labels = __CTA_LABELS__;
  const text = (el) => String(el.innerText || (el.matches("input") ? el.value : "") || "")
    .replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== "none" && style.visibility !== "hidden";
  };
  const disabled = (el) => el.hasAttribute("disabled") ||
    el.getAttribute("aria-disabled") === "true" ||
    el.classList.contains("disabled") ||
    el.classList.contains("is-disabled") ||
    el.classList.contains("unavailable");
  // Read the known selected widgets if still displayed on the next step.
  // The next screen may remove them: missing widgets mean unknown context.
  const targetDate = Array.from(document.querySelectorAll(".date-box.selected"))
    .filter(el => visible(el) && text(el).startsWith(expected.date)).length;
  const targetRoom = Array.from(document.querySelectorAll(".space-box1.selected"))
    .filter(el => visible(el) && text(el).includes(expected.room)).length;
  const targetTime = Array.from(document.querySelectorAll(
    ".time-box2.selected[data-param1]"))
    .filter(el => visible(el) && el.getAttribute("data-param1") === expected.slot).length;
  // Includes non-native div controls because NCL uses div for booking UI.
  // The text must be an exact allowlisted CTA: no arbitrary DOM text emitted.
  const nodes = Array.from(document.querySelectorAll(
    "button, a, input[type='button'], input[type='submit'], [role='button'], div, span"))
    .filter(el => visible(el) && labels.includes(text(el)))
    .filter(el => !Array.from(el.children).some(child =>
      visible(child) && text(child) === text(el)))
    .slice(0, 200);
  const actions = labels.map(label => {
    const found = nodes.filter(el => text(el) === label);
    return {label, count: found.length, disabled_count: found.filter(disabled).length};
  });
  return {
    host: location.hostname, source: "ncl_checkout_dom_v1",
    selected: {date_count: targetDate, room_count: targetRoom, slot_count: targetTime},
    actions
  };
})()"""


def checkout_script(day, slot):
    """Return a fixed-target DOM-only inspector, never a reservation action."""
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("Invalid checkout date")
    if slot not in VALID_SLOTS:
        raise ValueError("Unsupported music-room slot")
    expected = {"date": day.strftime("%m/%d"), "room": ROOM, "slot": slot}
    return (CHECKOUT_JS.replace("__EXPECTED__", json.dumps(expected, ensure_ascii=False))
            .replace("__CTA_LABELS__", json.dumps(CTA_LABELS, ensure_ascii=False)))


def assess_checkout(raw):
    """Fail closed. Report CTA presence only; never authorize booking."""
    result = {
        "status": "BLOCKED", "reason": "INVALID_CHECKOUT_EVIDENCE",
        "selected_target_verified": False, "final_reservation_action_visible": False,
        "actions": [], "can_click": False, "can_submit": False,
        "booking_verified": False
    }
    if (not isinstance(raw, dict) or raw.get("host") != NCL_HOST or
            raw.get("source") != SOURCE):
        return result
    selected = raw.get("selected")
    actions = raw.get("actions")
    if not isinstance(selected, dict) or not isinstance(actions, list):
        return result
    for name in ("date_count", "room_count", "slot_count"):
        if type(selected.get(name)) is not int or not 0 <= selected[name] <= 200:
            return result
    if len(actions) != len(CTA_LABELS):
        return result
    safe_actions = []
    for row, label in zip(actions, CTA_LABELS):
        if (not isinstance(row, dict) or row.get("label") != label or
                type(row.get("count")) is not int or
                type(row.get("disabled_count")) is not int or
                not 0 <= row["disabled_count"] <= row["count"] <= 200):
            return result
        safe_actions.append({"label": label, "count": row["count"],
                             "disabled_count": row["disabled_count"]})
    context = all(selected[name] == 1 for name in
                  ("date_count", "room_count", "slot_count"))
    final_labels = set(CTA_LABELS) - {"下一步"}
    final_visible = any(a["label"] in final_labels and
                        a["count"] > a["disabled_count"] for a in safe_actions)
    result["actions"] = safe_actions
    result["selected_target_verified"] = context
    result["final_reservation_action_visible"] = final_visible
    result["reason"] = ("FINAL_CTA_PRESENT_CONTEXT_MATCHED"
                        if context and final_visible else
                        "FINAL_CTA_VISIBLE_CONTEXT_UNVERIFIED"
                        if final_visible else
                        "FINAL_CTA_NOT_FOUND_OR_DISABLED")
    result["status"] = "OBSERVED_ONLY" if context and final_visible else "BLOCKED"
    return result
