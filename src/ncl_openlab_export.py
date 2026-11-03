# -*- coding: utf-8 -*-
"""Opt-in, privacy-minimized export for one NCL OPEN LAB DOM observation.

Exports only the validated evidence whitelist; never account data, page HTML,
credentials, cookies, URLs, or raw free-form DOM text. No network operations.
"""
import json
from datetime import date, datetime
from pathlib import Path

from ncl_openlab_evidence import validate_evidence
from ncl_openlab_slots import parse_slot_priority

EVIDENCE_FILENAME = "ncl_openlab_evidence.json"


def make_capture(raw_evidence, target_date, priorities):
    """Validate and normalize a privacy-safe snapshot; no availability claims."""
    if not isinstance(target_date, date) or isinstance(target_date, datetime):
        raise ValueError("target_date must be a date")
    safe = validate_evidence(raw_evidence)
    return {
        "schema_version": 1,
        "status": "UNVERIFIED_DOM_ONLY",
        "target_date": target_date.isoformat(),
        "room": "音樂創作室",
        "priorities": list(parse_slot_priority(priorities)),
        "availability_verified": False,
        "evidence": safe,
    }


def save_capture(directory, capture):
    """Write once to a fixed ignored filename; never overwrite evidence."""
    if not isinstance(capture, dict) or capture.get("schema_version") != 1:
        raise ValueError("Invalid capture")
    # Revalidate before serialization, to prevent arbitrary user/page fields.
    normalized = make_capture(
        capture.get("evidence"),
        date.fromisoformat(capture["target_date"]),
        capture.get("priorities"),
    )
    filename = Path(directory) / EVIDENCE_FILENAME
    with filename.open("x", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return filename
