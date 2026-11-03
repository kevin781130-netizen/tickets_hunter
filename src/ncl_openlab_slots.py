# -*- coding: utf-8 -*-
"""Read-only priority plan for OPEN LAB room *time slots*, not seats.

Observed DOM text is not proof of availability. This module cannot click or
submit a booking; it only orders inspection results for the requested slots.
"""
from ncl_openlab_guard import VALID_SLOTS, assess_probe
from ncl_openlab_status import classify_time_state


def parse_slot_priority(raw=None):
    """Parse comma-separated preferred times (first item has highest priority)."""
    if raw is None:
        return VALID_SLOTS
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        raise ValueError("slot priority must be text or a sequence")
    if not values or any(not isinstance(x, str) or x not in VALID_SLOTS for x in values):
        raise ValueError("invalid slot; expected one of: " + ", ".join(VALID_SLOTS))
    if len(set(values)) != len(values):
        raise ValueError("duplicate time slots are not allowed")
    return tuple(values)


def plan_time_slots(snapshot, target_day, priority=None):
    """Report only observable time candidates, in user-specified order.

    'first_observed' is for human review, NEVER an automatic selection or
    availability claim. Every report stays read-only and fail-closed.
    """
    ordered = parse_slot_priority(priority)
    checks = {slot: assess_probe(snapshot, target_day, slot) for slot in ordered}
    time_states = {slot: classify_time_state(snapshot, slot, checks[slot]) for slot in ordered}
    observed = [slot for slot in ordered if checks[slot]["status"] == "OBSERVED_ONLY"]
    return {
        "space": "音樂創作室",
        "priority": list(ordered),
        "first_observed": observed[0] if observed else None,
        "observed_slots": observed,
        "checks": checks,
        "time_states": time_states,
        "status": "OBSERVED_NOT_VERIFIED" if observed else "BLOCKED",
        "availability_verified": False,
        "can_select_time": False,
        "can_submit": False,
    }
