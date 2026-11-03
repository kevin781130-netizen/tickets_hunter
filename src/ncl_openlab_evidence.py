# -*- coding: utf-8 -*-
"""Sanitized, read-only DOM evidence for NCL OPEN LAB room time windows.

No credentials, page HTML, free-form text, user identifiers, cookies or
reservation actions are captured. Slot labels and status-hint tokens only.
"""
import json

from ncl_openlab_guard import NCL_HOST, VALID_SLOTS

# Page-scope, DOM read only. No clicks, navigation, network calls or storage.
EVIDENCE_JS = r"""(() => {
  const slots = __SLOTS__;
  const normalize = (s) => String(s || "").replace(/\s/g, "")
      .replace(/[～~–—－至]/g, "-");
  const roots = Array.from(document.querySelectorAll(".time-box[data-param1], .time-box2[data-param1]"))
    .slice(0, 16000);
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 &&
        style.visibility !== "hidden" && style.display !== "none";
  };
  const safeTag = (el) => el ? el.tagName.toLowerCase() : null;
  const flags = (el) => {
    const control = el.closest("button, label, input, a, [role='button'], [role='radio']") || el;
    const section = el; // Isolate each time-box; never infer from sibling slots.
    const text = String(section.innerText || "").slice(0, 240);
    const mixed = slots.filter((s) => normalize(text).includes(normalize(s))).length > 1;
    const statuses = ["已滿", "額滿", "名額已滿", "不可預約", "可預約",
                      "開放預約", "尚有名額", "候補"];
    const classDisabled = (n) => n && n.classList &&
        Array.from(n.classList).some((c) => /^(disabled|is-disabled|unavailable)$/i.test(c));
    const disabled = Boolean(control.disabled === true ||
        control.getAttribute("disabled") !== null ||
        control.getAttribute("aria-disabled") === "true" ||
        classDisabled(control) || classDisabled(el));
    return {
      tag: safeTag(el),
      control_tag: safeTag(control),
      role: ["button", "radio", "checkbox"].includes(control.getAttribute("role"))
        ? control.getAttribute("role") : null,
      disabled_ui_hint: disabled,
      aria_selected: control.getAttribute("aria-selected") === "true",
      checked: control.checked === true || control.getAttribute("aria-checked") === "true",
      mixed_slot_context: mixed,
      status_hints: mixed ? [] : statuses.filter((s) => text.includes(s)),
      class_hints: ["time-box", "time-box2", "book", "disabled", "reserving", "selected",
                    "is-disabled", "unavailable"].filter((c) => el.classList.contains(c))
    };
  };
  const matches = (slot) => roots.filter((el) =>
      visible(el) && el.getAttribute("data-param1") === slot);
  const roomNodes = Array.from(document.querySelectorAll(".space-box1"))
    .filter((el) => visible(el) &&
      String(el.innerText || "").includes("音樂創作室")).length;
  return {
    host: location.hostname,
    room_label_candidates: Math.min(roomNodes, 100),
    times: slots.map((slot) => {
      const found = matches(slot);
      return {slot, count: found.length,
        nodes: found.slice(0, 6).map(flags),
        truncated: found.length > 6};
    })
  };
})()"""


def evidence_script(slots=VALID_SLOTS):
    """Produce an isolated JS expression with a trusted fixed slot allowlist."""
    if (not isinstance(slots, (list, tuple)) or not slots or
            len(slots) != len(set(slots)) or
            any(not isinstance(s, str) or s not in VALID_SLOTS for s in slots)):
        raise ValueError("Unexpected OPEN LAB time slots")
    return EVIDENCE_JS.replace("__SLOTS__", json.dumps(slots, ensure_ascii=False))


def validate_evidence(data):
    """Fail closed before serializing data from the web page into diagnostics."""
    if not isinstance(data, dict) or data.get("host") != NCL_HOST:
        raise ValueError("Unexpected NCL origin")
    rows = data.get("times")
    if not isinstance(rows, list) or len(rows) != len(VALID_SLOTS):
        raise ValueError("Incomplete slot evidence")
    result = {"host": NCL_HOST, "room_label_candidates": 0, "times": []}
    rooms = data.get("room_label_candidates")
    if type(rooms) is not int or not 0 <= rooms <= 100:
        raise ValueError("Invalid room label count")
    result["room_label_candidates"] = rooms
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid slot evidence")
        slot, count, nodes = row.get("slot"), row.get("count"), row.get("nodes")
        if slot not in VALID_SLOTS or slot in seen:
            raise ValueError("Unexpected slot or duplicate")
        if type(count) is not int or not 0 <= count <= 16000:
            raise ValueError("Invalid candidate count")
        if type(row.get("truncated")) is not bool or not isinstance(nodes, list):
            raise ValueError("Invalid node evidence")
        if len(nodes) > 6 or len(nodes) != min(count, 6):
            raise ValueError("Inconsistent node count")
        clean = []
        for n in nodes:
            if not isinstance(n, dict):
                raise ValueError("Invalid evidence node")
            allowed_tags = {None, "button", "a", "label", "span", "div",
                            "input", "td", "li"}
            if n.get("tag") not in allowed_tags or n.get("control_tag") not in allowed_tags:
                raise ValueError("Unexpected HTML tag")
            if n.get("role") not in {None, "button", "radio", "checkbox"}:
                raise ValueError("Unexpected role")
            for field in ("disabled_ui_hint", "aria_selected", "checked", "mixed_slot_context"):
                if type(n.get(field)) is not bool:
                    raise ValueError("Invalid DOM flag")
            hints = n.get("status_hints")
            allowed_hints = {"已滿", "額滿", "名額已滿", "不可預約", "可預約",
                             "開放預約", "尚有名額", "候補"}
            if not isinstance(hints, list) or any(h not in allowed_hints for h in hints):
                raise ValueError("Unexpected status hint")
            clean.append({key: n[key] for key in (
                "tag", "control_tag", "role", "disabled_ui_hint",
                "aria_selected", "checked", "mixed_slot_context")})
            clean[-1]["status_hints"] = sorted(set(hints))
            class_hints = n.get("class_hints")
            if class_hints is not None:
                allowed_classes = {"time-box", "time-box2", "book", "disabled", "reserving", "selected",
                                   "is-disabled", "unavailable"}
                if (not isinstance(class_hints, list)
                        or any(not isinstance(c, str) or c not in allowed_classes
                               for c in class_hints)):
                    raise ValueError("Unexpected CSS class")
                clean[-1]["class_hints"] = sorted(set(class_hints))
        result["times"].append({
            "slot": slot, "count": count, "nodes": clean,
            "truncated": row["truncated"]
        })
        seen.add(slot)
    if seen != set(VALID_SLOTS):
        raise ValueError("Missing slot evidence")
    return result
