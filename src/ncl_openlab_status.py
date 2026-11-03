# -*- coding: utf-8 -*-
"""Conservative, read-only status labels for NCL room *time slots*.

A visible or clickable time does NOT mean the reservation is available.
Never interpret the site's business status without site-specific evidence.
"""


def classify_time_state(snapshot, slot, assessment):
    """Classify DOM evidence without claiming availability or booking success.

    assessment is produced by the existing fail-closed date/room/slot guard.
    An explicitly disabled control is not necessarily a fully booked slot.
    """
    outcome = {
        "state": "UNKNOWN",
        "evidence": "UNVERIFIED",
        "availability_verified": False,
        "can_book": False,
    }
    if not isinstance(assessment, dict):
        return outcome
    reason = assessment.get("reason")
    if assessment.get("status") == "OBSERVED_ONLY":
        return {**outcome, "state": "CANDIDATE_UNVERIFIED",
                "evidence": "ONE_VISIBLE_INTERACTIVE_CANDIDATE"}
    if reason == "SLOT_NOT_FOUND":
        return {**outcome, "state": "NOT_DISPLAYED", "evidence": reason}
    if reason == "SLOT_AMBIGUOUS":
        return {**outcome, "state": "AMBIGUOUS", "evidence": reason}
    if reason != "SLOT_DISABLED_OR_UNKNOWN":
        return {**outcome, "evidence": reason or "GUARD_BLOCKED"}
    if not isinstance(snapshot, dict):
        return outcome
    groups = snapshot.get("results")
    nodes = groups.get(slot) if isinstance(groups, dict) else None
    if isinstance(nodes, list) and len(nodes) == 1:
        node = nodes[0]
        if isinstance(node, dict) and node.get("disabled") is True:
            return {**outcome, "state": "CONTROL_DISABLED",
                    "evidence": "EXPLICIT_DISABLED_CONTROL"}
    return {**outcome, "evidence": "DISABLED_STATE_NOT_VERIFIED"}
