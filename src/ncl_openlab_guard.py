# -*- coding: utf-8 -*-
"""Fail-closed, side-effect-free interpretation of NCL OPEN LAB DOM probe data.

This module ONLY inspects previously collected, minimal DOM metadata. It never
clicks elements, sends network requests, or decides to submit a reservation.
"""
from datetime import date, datetime

NCL_HOST = "spms.ncl.edu.tw"
ROOM = "音樂創作室"
VALID_SLOTS = ("09:00-12:00", "13:00-16:00", "17:00-20:00")


def assess_probe(snapshot, target_day, target_slot):
    """Assess exact target presence. Always requires manual confirmation.

    Result status is BLOCKED or OBSERVED_ONLY. OBSERVED_ONLY is not proof of
    vacancy, selected state, or permission to automate a booking.
    """
    result = {"status": "BLOCKED", "reason": "", "checks": {},
              "can_book": False, "can_click": False}
    if not isinstance(target_day, date) or isinstance(target_day, datetime):
        result["reason"] = "INVALID_DATE"
        return result
    if target_slot not in VALID_SLOTS:
        result["reason"] = "INVALID_SLOT"
        return result
    if not isinstance(snapshot, dict) or snapshot.get("host") != NCL_HOST:
        result["reason"] = "HOST_MISMATCH"
        return result

    groups = snapshot.get("results")
    if not isinstance(groups, dict):
        result["reason"] = "MISSING_RESULTS"
        return result

    for label, needle in (
        ("date", target_day.strftime("%m/%d")),
        ("room", ROOM),
        ("slot", target_slot),
    ):
        candidates = groups.get(needle)
        if not isinstance(candidates, list) or len(candidates) == 0:
            result["checks"][label] = "NOT_FOUND"
            result["reason"] = label.upper() + "_NOT_FOUND"
            return result
        if len(candidates) != 1:
            result["checks"][label] = "AMBIGUOUS"
            result["reason"] = label.upper() + "_AMBIGUOUS"
            return result
        node = candidates[0]
        if not isinstance(node, dict):
            result["reason"] = label.upper() + "_INVALID_NODE"
            return result
        sample = node.get("sample")
        if not isinstance(sample, str) or needle not in sample:
            result["checks"][label] = "TEXT_MISMATCH"
            result["reason"] = label.upper() + "_TEXT_MISMATCH"
            return result
        if node.get("disabled") is not False:
            result["checks"][label] = "DISABLED_OR_UNKNOWN"
            result["reason"] = label.upper() + "_DISABLED_OR_UNKNOWN"
            return result
        if node.get("clickable") is not True and node.get("selected") is not True:
            result["checks"][label] = "NOT_ACTIONABLE"
            result["reason"] = label.upper() + "_NOT_ACTIONABLE"
            return result
        result["checks"][label] = "SINGLE_ENABLED_CANDIDATE"

    result["status"] = "OBSERVED_ONLY"
    result["reason"] = "SINGLE_CANDIDATE_EACH; NOT VERIFIED AS AVAILABLE"
    return result
