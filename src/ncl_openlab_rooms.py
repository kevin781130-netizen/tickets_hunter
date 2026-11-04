# -*- coding: utf-8 -*-
"""Data-driven room profiles for the NCL OPEN LAB booking engine.

All per-room differences live in ``ncl_openlab_rooms.json``. This module only
loads, validates and classifies that data. It never touches a browser, sends
requests, clicks or submits anything.

Terminology:
  flow    - the DOM interaction model (slot selector, which class means
            "selected", whether a positive 'book' class is required before
            clicking). Rooms sharing a flow share one engine code path and one
            set of full-walkthrough tests.
  profile - one room: how to find its tile, which slots it offers, how the
            final confirmation page names it, and what live evidence exists.
"""
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CONFIG_ENV = "NCL_ROOMS_CONFIG"
DEFAULT_CONFIG = Path(__file__).with_name("ncl_openlab_rooms.json")
SCHEMA_VERSION = 1
LIVE_STATES = ("LIVE_VERIFIED", "NOT_VERIFIED")
TILE_KINDS = ("includes", "regex")
SLOT_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
# Keep configured patterns simple; they are executed inside the page.
_FORBIDDEN_REGEX = ("(?<", "(?P", "(?#", ")+", ")*", "){", "\\1", "\\2")


class RoomConfigError(ValueError):
    """Raised for any invalid or unsafe room configuration."""


@dataclass(frozen=True)
class FlowSpec:
    name: str
    description: str
    slot_selector: str
    slot_requires_book_class: bool
    book_class_marks_selected: bool

    @property
    def signature(self):
        return (self.slot_selector, self.slot_requires_book_class,
                self.book_class_marks_selected)


@dataclass(frozen=True)
class RoomProfile:
    key: str
    label: str
    ui_label: str
    entry_label: str
    flow: FlowSpec
    tile_kind: str
    tile_value: str
    summary_text_all: tuple
    summary_regex_all: tuple
    sample_tile_label: str
    slots: tuple
    default_all_slots: bool
    single_slot_option: bool
    submit_requires_ack: bool
    live: str
    live_notes: str
    source: str

    def tile_matches(self, text):
        """Python mirror of the in-page tile matcher (used by offline tests)."""
        if self.tile_kind == "regex":
            return re.search(self.tile_value, text) is not None
        return self.tile_value in text

    def summary_matches(self, text):
        """Python mirror of the in-page confirmation-page room matcher."""
        squeezed = re.sub(r"\s+", "", text)
        return (all(re.sub(r"\s+", "", t) in squeezed for t in self.summary_text_all)
                and all(re.search(p, text) for p in self.summary_regex_all))

    def task_profile(self):
        """Minimal, JSON-serialisable profile handed to the page script."""
        return {
            "key": self.key,
            "entryLabel": self.entry_label,
            "tileKind": self.tile_kind,
            "tileValue": self.tile_value,
            "summaryTextAll": list(self.summary_text_all),
            "summaryRegexAll": list(self.summary_regex_all),
            "slotSelector": self.flow.slot_selector,
            "slotRequiresBook": self.flow.slot_requires_book_class,
            "bookMarksSelected": self.flow.book_class_marks_selected,
        }


@dataclass(frozen=True)
class RoomRegistry:
    flows: dict
    rooms: dict

    @property
    def keys(self):
        return tuple(self.rooms)

    def room(self, key):
        try:
            return self.rooms[key]
        except KeyError:
            raise ValueError("unsupported room: " + str(key)) from None

    def by_flow(self):
        grouped = {name: [] for name in self.flows}
        for profile in self.rooms.values():
            grouped[profile.flow.name].append(profile)
        return grouped

    def flow_for_signature(self, signature):
        for flow in self.flows.values():
            if flow.signature == tuple(signature):
                return flow
        return None


def _require(condition, message):
    if not condition:
        raise RoomConfigError(message)


def _text(value, field, limit=120):
    _require(isinstance(value, str) and value.strip() and len(value) <= limit,
             f"{field} must be a non-empty string up to {limit} chars")
    # Draft entries produced by the inventory tool mark unknown facts with TODO.
    _require("TODO" not in value, f"{field} still contains a TODO placeholder")
    return value


def _flag(value, field):
    _require(isinstance(value, bool), f"{field} must be true or false")
    return value


def _pattern(value, field):
    _text(value, field, 80)
    _require(not any(token in value for token in _FORBIDDEN_REGEX),
             f"{field} uses an unsupported regex construct")
    try:
        re.compile(value)
    except re.error as exc:
        raise RoomConfigError(f"{field} is not a valid pattern: {exc}") from None
    return value


def _parse_slots(spec, field):
    _require(isinstance(spec, dict), f"{field} must be an object")
    kind = spec.get("kind")
    if kind == "list":
        values = spec.get("values")
        _require(isinstance(values, list) and values, f"{field}.values must be a list")
        slots = tuple(values)
    elif kind == "hourly":
        start, end = spec.get("start"), spec.get("end")
        _require(all(type(x) is int for x in (start, end)) and 0 <= start < end <= 24,
                 f"{field} hourly start/end must be integers within 0-24")
        slots = tuple(f"{h:02d}:00-{h + 1:02d}:00" for h in range(start, end))
    else:
        raise RoomConfigError(f"{field}.kind must be 'list' or 'hourly'")
    _require(all(isinstance(s, str) and SLOT_RE.match(s) for s in slots),
             f"{field} contains an invalid slot label")
    _require(len(set(slots)) == len(slots), f"{field} contains duplicate slots")
    return slots


def _parse_flow(name, raw):
    _require(KEY_RE.match(str(name)), f"flow name {name!r} is invalid")
    _require(isinstance(raw, dict), f"flow {name} must be an object")
    selector = _text(raw.get("slot_selector"), f"flow {name}.slot_selector", 60)
    _require(re.fullmatch(r"\.[a-z0-9-]+\[data-param1\]", selector) is not None,
             f"flow {name}.slot_selector must be '.class[data-param1]'")
    return FlowSpec(
        name=name,
        description=_text(raw.get("description"), f"flow {name}.description", 200),
        slot_selector=selector,
        slot_requires_book_class=_flag(raw.get("slot_requires_book_class"),
                                       f"flow {name}.slot_requires_book_class"),
        book_class_marks_selected=_flag(raw.get("book_class_marks_selected"),
                                        f"flow {name}.book_class_marks_selected"),
    )


def _parse_room(key, raw, flows):
    _require(KEY_RE.match(str(key)), f"room key {key!r} is invalid")
    _require(isinstance(raw, dict), f"room {key} must be an object")
    where = f"room {key}"
    flow_name = raw.get("flow")
    _require(flow_name in flows, f"{where}.flow {flow_name!r} is not a defined flow")
    tile = raw.get("tile_match")
    _require(isinstance(tile, dict) and tile.get("kind") in TILE_KINDS,
             f"{where}.tile_match.kind must be one of {TILE_KINDS}")
    tile_value = (_pattern(tile.get("value"), f"{where}.tile_match.value")
                  if tile["kind"] == "regex"
                  else _text(tile.get("value"), f"{where}.tile_match.value", 40))
    summary = raw.get("summary_match")
    _require(isinstance(summary, dict), f"{where}.summary_match must be an object")
    text_all = summary.get("text_all")
    regex_all = summary.get("regex_all")
    _require(isinstance(text_all, list) and text_all,
             f"{where}.summary_match.text_all needs at least one entry")
    _require(isinstance(regex_all, list), f"{where}.summary_match.regex_all must be a list")
    evidence = raw.get("evidence")
    _require(isinstance(evidence, dict) and evidence.get("live") in LIVE_STATES,
             f"{where}.evidence.live must be one of {LIVE_STATES}")
    profile = RoomProfile(
        key=key,
        label=_text(raw.get("label"), f"{where}.label", 40),
        ui_label=_text(raw.get("ui_label"), f"{where}.ui_label", 60),
        entry_label=_text(raw.get("entry_label"), f"{where}.entry_label", 40),
        flow=flows[flow_name],
        tile_kind=tile["kind"],
        tile_value=tile_value,
        summary_text_all=tuple(_text(t, f"{where}.summary_match.text_all", 40)
                               for t in text_all),
        summary_regex_all=tuple(_pattern(p, f"{where}.summary_match.regex_all")
                                for p in regex_all),
        sample_tile_label=_text(raw.get("sample_tile_label"),
                                f"{where}.sample_tile_label", 80),
        slots=_parse_slots(raw.get("slots"), f"{where}.slots"),
        default_all_slots=_flag(raw.get("default_all_slots"), f"{where}.default_all_slots"),
        single_slot_option=_flag(raw.get("single_slot_option"),
                                 f"{where}.single_slot_option"),
        submit_requires_ack=_flag(raw.get("submit_requires_ack"),
                                  f"{where}.submit_requires_ack"),
        live=evidence["live"],
        live_notes=_text(evidence.get("live_notes"), f"{where}.evidence.live_notes", 300),
        source=_text(evidence.get("source"), f"{where}.evidence.source", 200),
    )
    _require(profile.tile_matches(profile.sample_tile_label),
             f"{where}: tile_match does not match its own sample_tile_label")
    _require(profile.summary_matches(profile.sample_tile_label),
             f"{where}: summary_match does not match its own sample_tile_label")
    return profile


def parse_config(data):
    """Validate a config mapping and return a RoomRegistry (fail closed)."""
    _require(isinstance(data, dict), "config root must be an object")
    _require(data.get("schema_version") == SCHEMA_VERSION,
             f"schema_version must be {SCHEMA_VERSION}")
    raw_flows, raw_rooms = data.get("flows"), data.get("rooms")
    _require(isinstance(raw_flows, dict) and raw_flows, "flows must be a non-empty object")
    _require(isinstance(raw_rooms, dict) and raw_rooms, "rooms must be a non-empty object")
    flows = {name: _parse_flow(name, raw) for name, raw in raw_flows.items()}
    signatures = [flow.signature for flow in flows.values()]
    _require(len(set(signatures)) == len(signatures),
             "two flows have identical behaviour; merge them")
    rooms = {key: _parse_room(key, raw, flows) for key, raw in raw_rooms.items()}
    # A tile matcher must identify exactly one room. Otherwise the engine could
    # click the neighbouring room, which is the costliest failure mode.
    for key, profile in rooms.items():
        for other_key, other in rooms.items():
            if other_key != key and profile.tile_matches(other.sample_tile_label):
                raise RoomConfigError(
                    f"room {key} tile_match also matches room {other_key}")
    return RoomRegistry(flows=flows, rooms=rooms)


def load_config(path=None):
    target = Path(path or os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RoomConfigError(f"cannot read room config {target.name}: {exc}") from None
    return parse_config(data)


@lru_cache(maxsize=1)
def get_registry():
    return load_config()


def classify_flow(features, registry=None):
    """Map observed slot-tile behaviour to a known flow name, or None.

    ``features`` needs slot_selector, slot_requires_book_class and
    book_class_marks_selected. None means "new flow": it needs its own
    full-walkthrough fixture and live verification before it can be trusted.
    """
    registry = registry or get_registry()
    try:
        signature = (features["slot_selector"],
                     features["slot_requires_book_class"],
                     features["book_class_marks_selected"])
    except (KeyError, TypeError):
        return None
    flow = registry.flow_for_signature(signature)
    return flow.name if flow else None


def support_matrix(registry=None):
    """Rows for the human-readable support report (never claims more than evidence)."""
    registry = registry or get_registry()
    rows = []
    for profile in registry.rooms.values():
        rows.append({
            "room": profile.key,
            "label": profile.label,
            "flow": profile.flow.name,
            "slots": len(profile.slots),
            "offline": "COVERED_BY_OFFLINE_TESTS",
            "live": profile.live,
            "status": ("SUPPORTED_LIVE_VERIFIED" if profile.live == "LIVE_VERIFIED"
                       else "SUPPORTED_OFFLINE_ONLY_LIVE_NOT_VERIFIED"),
            "submit_requires_ack": profile.submit_requires_ack,
            "notes": profile.live_notes,
        })
    return rows
