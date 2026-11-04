"""Prove the data-driven engine behaves exactly like the verified pre-refactor code.

tests/fixtures/legacy_autobook_4d0da47.py is a frozen copy of the P03-verified
implementation (commit 4d0da47). The same fixtures, the same CLI arguments and
the same parsing inputs are fed to both; results must be identical.
"""
import contextlib
import importlib.util
import json
import sys
import unittest
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import ncl_browser as browser
import ncl_fixtures as fx
import ncl_openlab_autobook as new
from ncl_openlab_rooms import get_registry

_spec = importlib.util.spec_from_file_location(
    "legacy_autobook", HERE / "fixtures" / "legacy_autobook_4d0da47.py")
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)

DAY = date(2026, 11, 11)
REGISTRY = get_registry()
LEGACY_ROOMS = ("music", "p03")  # the two rooms the frozen code knows about
# Website behaviour as OBSERVED live (docs/ncl_openlab_probe.md, 8th/14th cut).
# Pinned here, NOT derived from the config, so a config error cannot hide itself.
OBSERVED_SITE = {
    "music": {"slot_class": "time-box2", "requires_book": True, "mark": "selected"},
    "p03": {"slot_class": "time-box", "requires_book": False, "mark": "book"},
}


def run_main(module, argv):
    """Return ('exit', code) or ('ok', kwargs passed to autobook)."""
    with (patch.object(sys, "argv", ["app"] + argv),
          patch.object(module.asyncio, "run", return_value="MOCK") as runner,
          contextlib.redirect_stdout(StringIO()),
          contextlib.redirect_stderr(StringIO())):
        try:
            module.main()
        except SystemExit as exc:
            return ("exit", exc.code)
    coro = runner.call_args.args[0]
    try:
        keys = ("day", "priorities", "auto_submit", "now_mode", "mode",
                "accept_terms", "reserve_two", "retry_interval", "retry_window")
        values = coro.cr_frame.f_locals
        return ("ok", {k: values[k] for k in keys})
    finally:
        coro.close()


class StaticParityTests(unittest.TestCase):
    def test_public_constants_match(self):
        self.assertEqual(new.PHASES, legacy.PHASES)
        # Rooms added later via config may extend the tuple; the originals stay first.
        self.assertEqual(new.ROOM_MODES[:len(legacy.ROOM_MODES)], legacy.ROOM_MODES)
        self.assertEqual(new.P03_SLOTS, legacy.P03_SLOTS)
        for name in ("PRE_REFRESH_SECONDS", "RETRY_INTERVAL_SECONDS",
                     "RETRY_WINDOW_SECONDS", "RETRYABLE_BEFORE_SUBMIT"):
            self.assertEqual(getattr(new, name), getattr(legacy, name), name)

    def test_release_timing_matches(self):
        for day in (date(2026, 11, 11), date(2026, 3, 1), date(2027, 1, 1)):
            self.assertEqual(new.release_time(day), legacy.release_time(day))

    def test_slot_parsers_match_on_valid_and_invalid_input(self):
        raws = ["13:00-14:00", "13:00-14:00,14:00-15:00", "", "13:00-14:00,13:00-14:00",
                "13:00-16:00", "13:30-14:30", "09:00-10:00,19:00-20:00", None, 5,
                ",".join(legacy.P03_SLOTS), ",".join(legacy.P03_SLOTS) + ",09:00-10:00"]
        for raw in raws:
            outcome = []
            for fn in (legacy.parse_p03_priorities, new.parse_p03_priorities):
                try:
                    outcome.append(fn(raw))
                except ValueError:
                    outcome.append("ValueError")
            self.assertEqual(outcome[0], outcome[1], raw)

    def test_music_priority_parsing_matches(self):
        raws = [None, "13:00-16:00", "17:00-20:00,09:00-12:00", "09:00-12:00,09:00-12:00",
                "09:00-10:00", "", "13:00-16:00,17:00-20:00,09:00-12:00"]
        for raw in raws:
            outcome = []
            for fn in (lambda r: legacy.parse_slot_priority(r),
                       lambda r: new.parse_room_priorities("music", r)):
                try:
                    outcome.append(fn(raw))
                except ValueError:
                    outcome.append("ValueError")
            self.assertEqual(outcome[0], outcome[1], raw)

    def test_action_script_validation_matches(self):
        from datetime import datetime
        cases = [("slot", DAY, "13:00-16:00", "music"), ("slot", DAY, "13:00-14:00", "p03"),
                 ("slot", DAY, "13:00-14:00", "music"), ("slot", DAY, "13:00-16:00", "p03"),
                 ("bogus", DAY, "13:00-16:00", "music"), ("slot", DAY, "13:00-16:00", "p02"),
                 ("date", datetime(2026, 11, 11), "13:00-16:00", "music"),
                 ("date", "2026-11-11", "13:00-16:00", "music")]
        for args in cases:
            outcome = []
            for module in (legacy, new):
                try:
                    module.action_script(*args)
                    outcome.append("ok")
                except ValueError:
                    outcome.append("ValueError")
            self.assertEqual(outcome[0], outcome[1], args)

    def test_script_payload_keeps_all_legacy_fields(self):
        prefix, suffix = legacy.ACTION_JS.split("__TASK__")
        for mode, slot in (("music", "13:00-16:00"), ("p03", "13:00-14:00")):
            old = legacy.action_script("slot", DAY, slot, mode)
            old_task = json.loads(old[len(prefix):len(old) - len(suffix)])
            new_prefix, new_suffix = new.ACTION_JS.split("__TASK__")
            fresh = new.action_script("slot", DAY, slot, mode)
            new_task = json.loads(fresh[len(new_prefix):len(fresh) - len(new_suffix)])
            for key, value in old_task.items():
                self.assertEqual(new_task[key], value, (mode, key))


class ObservedContractTests(unittest.TestCase):
    """The config for the two live-observed rooms must equal the observed DOM contract."""

    def test_music_profile_matches_observed_dom(self):
        room = REGISTRY.room("music")
        self.assertEqual(room.flow.signature, (".time-box2[data-param1]", True, False))
        self.assertEqual((room.tile_kind, room.tile_value), ("includes", "音樂創作室"))
        self.assertEqual((room.summary_text_all, room.summary_regex_all), (("音樂創作室",), ()))
        self.assertEqual(room.entry_label, "音樂創作室")
        self.assertEqual(room.slots, ("09:00-12:00", "13:00-16:00", "17:00-20:00"))

    def test_p03_profile_matches_observed_dom(self):
        room = REGISTRY.room("p03")
        self.assertEqual(room.flow.signature, (".time-box[data-param1]", False, True))
        self.assertEqual((room.tile_kind, room.tile_value), ("regex", r"^P03(?:\s|$)"))
        self.assertEqual(room.summary_text_all, ("個人直播室",))
        self.assertEqual(room.summary_regex_all, (r"\bP03\b",))
        self.assertEqual(room.entry_label, "個人直播室")
        self.assertEqual(room.slots[0], "09:00-10:00")
        self.assertEqual(room.slots[-1], "19:00-20:00")
        self.assertEqual(len(room.slots), 11)


class CliParityTests(unittest.TestCase):
    ARGV = [
        ["--date", "2026-11-12"],
        ["--date", "2026-11-12", "--now", "--auto-submit"],
        ["--date", "2026-11-12", "--slots", "13:00-16:00,09:00-12:00", "--auto-submit"],
        ["--date", "2026-11-12", "--slots", "13:00-16:00,17:00-20:00", "--reserve-two"],
        ["--date", "2026-11-12", "--slots", "13:00-16:00,17:00-20:00", "--reserve-two",
         "--auto-submit", "--accept-terms", "--now"],
        ["--date", "2026-11-12", "--slot", "13:00-16:00"],
        ["--date", "2026-11-12", "--slots", "09:00-10:00"],
        ["--date", "2026-11-12", "--slots", "13:00-16:00,13:00-16:00"],
        ["--date", "2026-11-12", "--room", "p03"],
        ["--date", "2026-11-12", "--room", "p03", "--slot", "13:00-14:00"],
        ["--date", "2026-11-12", "--room", "p03", "--slot", "13:00-14:00", "--now", "--auto-submit"],
        ["--date", "2026-11-12", "--room", "p03", "--slot", "13:00-16:00"],
        ["--date", "2026-11-12", "--room", "p03", "--slots", "13:00-14:00,14:00-15:00"],
        ["--date", "2026-11-12", "--room", "p03", "--slots", "13:00-14:00,14:00-15:00",
         "--reserve-two", "--now", "--auto-submit"],
        ["--date", "2026-11-12", "--room", "p03", "--slot", "13:00-14:00",
         "--auto-submit", "--reserve-two"],
        ["--date", "2026-11-12", "--room", "p03", "--slot", "13:00-14:00", "--slots", "14:00-15:00"],
        ["--date", "2026-11-12", "--room", "p02", "--slot", "13:00-14:00"],
        ["--date", "2026-11-12", "--retry-interval", "1"],
        ["--date", "2026-11-12", "--retry-interval", "31"],
        ["--date", "2026-11-12", "--retry-window", "181"],
        ["--date", "2026-11-12", "--retry-interval", "5", "--retry-window", "60"],
        ["--date", "not-a-date"],
        [],
    ]

    def test_cli_behaviour_is_identical(self):
        for argv in self.ARGV:
            self.assertEqual(run_main(legacy, argv), run_main(new, argv), argv)


@unittest.skipUnless(browser.available(), "NOT_VERIFIED: headless Chromium unavailable")
class BrowserParityTests(unittest.TestCase):
    VARIANTS = (
        {}, {"slot_state": "disabled"}, {"slot_state": "no_book"}, {"dup_room": True},
        {"room_disabled": True}, {"date_disabled": True}, {"date_missing": True},
        {"next_button": False}, {"decoys": False},
        {"checkout": "wrong_room"}, {"checkout": "near_miss_room"},
        {"checkout": "wrong_date_attr"},
        {"checkout": "wrong_slot_attr"}, {"checkout": "occluded"},
        {"checkout": "missing_button"}, {"checkout": "duplicate_button"},
        {"result": "failure"}, {"result": "ambiguous"}, {"result": "wrong_slot"},
    )

    def test_every_phase_returns_the_same_code_as_the_verified_implementation(self):
        cases, index = [], {}
        for mode in LEGACY_ROOMS:
            profile = REGISTRY.room(mode)
            for slot in (profile.slots[0], profile.slots[len(profile.slots) // 2],
                         profile.slots[-1]):
                for n, variant in enumerate(self.VARIANTS):
                    html = fx.grid_html(REGISTRY, mode, DAY, site=OBSERVED_SITE[mode],
                                        **variant)
                    for label, module in (("legacy", legacy), ("new", new)):
                        case_id = f"{label}|{mode}|{slot}|{n}"
                        cases.append({"id": case_id, "html": html,
                                      "steps": fx.walk_steps(module.action_script, DAY, slot, mode)})
                    index[(mode, slot, n)] = variant
        results = browser.run_cases(cases)
        self.assertEqual(len(index) * 2, len(cases))
        for (mode, slot, n), variant in index.items():
            old = results[f"legacy|{mode}|{slot}|{n}"]
            fresh = results[f"new|{mode}|{slot}|{n}"]
            self.assertIsNone(old["error"], old["error"])
            self.assertIsNone(fresh["error"], fresh["error"])
            self.assertEqual(browser.codes(fresh), browser.codes(old), (mode, slot, variant))

    def test_lobby_entry_matches_for_both_legacy_rooms(self):
        cases = []
        for mode in LEGACY_ROOMS:
            for accept in (False, True):
                for dup in (None, REGISTRY.room(mode).entry_label):
                    html = fx.status_html(REGISTRY, dup_label=dup)
                    old_js = (legacy.ENTRY_JS
                              .replace("__ALLOW_AGREE__", "true" if accept else "false")
                              .replace("__ROOM_MODE__", json.dumps(mode)))
                    tag = f"{mode}|{accept}|{dup}"
                    for label, js in (("legacy", old_js), ("new", new.entry_script(mode, accept))):
                        cases.append({"id": f"{label}|{tag}", "html": html,
                                      "url": fx.NCL_URL_STATUS,
                                      "steps": [fx.step(js), fx.step("window.__opened")]})
        results = browser.run_cases(cases)
        for case in cases:
            if case["id"].startswith("new|"):
                tag = case["id"][4:]
                self.assertEqual(results[case["id"]]["steps"],
                                 results["legacy|" + tag]["steps"], tag)


if __name__ == "__main__":
    unittest.main()
