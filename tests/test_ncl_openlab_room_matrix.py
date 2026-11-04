"""Room x scenario matrix executed against REAL page scripts in headless Chromium.

Pages are synthetic fixtures generated from ncl_openlab_rooms.json (see
tests/ncl_fixtures.py). Every configured room gets the same checks, so adding
a room to the JSON adds its tests automatically; rooms that share a flow are
verified by differential checks instead of hand-written per-room tests.

If Node/Playwright/Chromium is unavailable these tests are SKIPPED, which the
report counts as NOT_VERIFIED, never as a pass.
"""
import json
import sys
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import ncl_browser as browser
import ncl_fixtures as fx
import ncl_openlab_autobook as app
from ncl_openlab_rooms import get_registry

DAY = date(2026, 11, 11)
REGISTRY = get_registry()
URL_OTHER = "https://other.example/NLT/co/media_discussion.jsp"


def slot_for(profile):
    """A representative slot: the middle of the room's allowlist."""
    return profile.slots[len(profile.slots) // 2]


def phase_steps(profile, phases, slot=None):
    slot = slot or slot_for(profile)
    return [fx.step(app.action_script(p, DAY, slot, profile.key)) for p in phases]


@unittest.skipUnless(browser.available(), "NOT_VERIFIED: headless Chromium unavailable")
class RoomMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = []
        cls.expect = {}

        def add(case_id, html, steps, expected=None, url=None):
            cases.append({"id": case_id, "html": html, "steps": steps,
                          **({"url": url} if url else {})})
            cls.expect[case_id] = expected

        for key, profile in REGISTRY.rooms.items():
            slot = slot_for(profile)
            flow = profile.flow
            base = lambda **kw: fx.grid_html(REGISTRY, key, DAY, **kw)  # noqa: E731
            # Full walkthrough through a real pointer click on the final button.
            add(f"{key}:walk", base(),
                fx.walk_steps(app.action_script, DAY, slot, key)
                + [fx.step("window.__booked")], None)
            # Every allowlisted slot can be selected in turn.
            add(f"{key}:all_slots", base(),
                phase_steps(profile, ("date", "room")) +
                [fx.step(app.action_script("slot", DAY, s, key)) for s in profile.slots])
            add(f"{key}:selected_rooms", base(),
                phase_steps(profile, ("date", "room")) +
                [fx.step("Array.from(document.querySelectorAll('.space-box1.selected'))"
                         ".map(e => e.innerText)")])
            # Negative fixtures: each must fail closed with the exact code.
            add(f"{key}:slot_disabled", base(slot_state="disabled"),
                phase_steps(profile, ("date", "room", "slot", "next")))
            add(f"{key}:slot_no_book", base(slot_state="no_book"),
                phase_steps(profile, ("date", "room", "slot")))
            add(f"{key}:dup_room", base(dup_room=True),
                phase_steps(profile, ("date", "room")))
            add(f"{key}:room_disabled", base(room_disabled=True),
                phase_steps(profile, ("date", "room")))
            add(f"{key}:date_disabled", base(date_disabled=True),
                phase_steps(profile, ("date",)))
            add(f"{key}:date_missing", base(date_missing=True),
                phase_steps(profile, ("date",)))
            add(f"{key}:no_next", base(next_button=False),
                phase_steps(profile, ("date", "room", "slot", "next")))
            for variant in ("wrong_room", "near_miss_room", "longer_code_room",
                            "wrong_date_attr", "wrong_slot_attr",
                            "occluded", "missing_button", "duplicate_button"):
                add(f"{key}:checkout_{variant}", base(checkout=variant),
                    phase_steps(profile, ("date", "room", "slot", "next", "submit")))
            add(f"{key}:double_submit", base(),
                phase_steps(profile, ("date", "room", "slot", "next", "submit", "submit")))
            for variant in ("failure", "ambiguous", "wrong_slot"):
                add(f"{key}:result_{variant}", base(result=variant),
                    fx.walk_steps(app.action_script, DAY, slot, key))
            add(f"{key}:wrong_host", base(), phase_steps(profile, ("date",)), url=URL_OTHER)
            # Lobby navigation uses the exact status label.
            add(f"{key}:entry", fx.status_html(REGISTRY),
                [fx.step(app.entry_script(key, True)), fx.step("window.__opened")],
                url=fx.NCL_URL_STATUS)
            add(f"{key}:entry_dup", fx.status_html(REGISTRY, dup_label=profile.entry_label),
                [fx.step(app.entry_script(key, True)), fx.step("window.__opened")],
                url=fx.NCL_URL_STATUS)
        cls.results = browser.run_cases(cases)

    def codes(self, case_id):
        result = self.results[case_id]
        self.assertIsNone(result["error"], result["error"])
        return browser.codes(result)

    def test_full_walkthrough_for_every_room(self):
        for key in REGISTRY.keys:
            codes = self.codes(f"{key}:walk")
            self.assertEqual(codes[:-1], fx.FULL_WALK_CODES, key)
            self.assertEqual(codes[-1], 1, f"{key}: final button must be activated once")

    def test_every_allowlisted_slot_is_selectable(self):
        for key, profile in REGISTRY.rooms.items():
            codes = self.codes(f"{key}:all_slots")
            self.assertEqual(codes[:2], ["CLICKED", "CLICKED"], key)
            self.assertEqual(codes[2:], ["CLICKED"] * len(profile.slots), key)

    def test_exactly_the_configured_room_is_selected(self):
        """Neighbouring rooms and decoy tiles must never be clicked."""
        for key, profile in REGISTRY.rooms.items():
            codes = self.codes(f"{key}:selected_rooms")
            self.assertEqual(codes[2], [profile.sample_tile_label], key)

    def test_disabled_slot_is_never_chosen_or_advanced(self):
        for key in REGISTRY.keys:
            self.assertEqual(self.codes(f"{key}:slot_disabled"),
                             ["CLICKED", "CLICKED", "SLOT_DISABLED", "TARGET_NOT_SELECTED"], key)

    def test_book_class_requirement_follows_the_flow(self):
        for key, profile in REGISTRY.rooms.items():
            expected = ("SLOT_NOT_BOOK_CLASS" if profile.flow.slot_requires_book_class
                        else "CLICKED")
            self.assertEqual(self.codes(f"{key}:slot_no_book")[2], expected, key)

    def test_ambiguous_or_disabled_targets_fail_closed(self):
        for key in REGISTRY.keys:
            self.assertEqual(self.codes(f"{key}:dup_room"), ["CLICKED", "ROOM_NOT_UNIQUE"], key)
            self.assertEqual(self.codes(f"{key}:room_disabled"), ["CLICKED", "ROOM_DISABLED"], key)
            self.assertEqual(self.codes(f"{key}:date_disabled"), ["DATE_DISABLED"], key)
            self.assertEqual(self.codes(f"{key}:date_missing"), ["DATE_NOT_UNIQUE"], key)
            self.assertEqual(self.codes(f"{key}:no_next")[3], "NEXT_NOT_ACTIONABLE", key)

    def test_final_confirmation_guards(self):
        expected = {
            "wrong_room": "SUMMARY_MISMATCH",
            "near_miss_room": "SUMMARY_MISMATCH",
            "wrong_date_attr": "SUBMIT_TARGET_MISMATCH",
            "wrong_slot_attr": "SUBMIT_TARGET_MISMATCH",
            "occluded": "SUBMIT_BUTTON_OCCLUDED",
            "missing_button": "SUBMIT_NOT_ACTIONABLE",
            "duplicate_button": "SUBMIT_NOT_ACTIONABLE",
        }
        for key, profile in REGISTRY.rooms.items():
            for variant, code in expected.items():
                self.assertEqual(self.codes(f"{key}:checkout_{variant}")[4], code,
                                 f"{key}/{variant}")
            # '縫紉機010' / 'P030' must not pass for room 01 / P03 (rooms with a code only).
            longer = fx.longer_code_label(profile.sample_tile_label) != profile.sample_tile_label
            self.assertEqual(self.codes(f"{key}:checkout_longer_code_room")[4],
                             "SUMMARY_MISMATCH" if longer else "READY_FOR_POINTER_CLICK", key)

    def test_submit_guard_is_one_shot(self):
        for key in REGISTRY.keys:
            codes = self.codes(f"{key}:double_submit")
            self.assertEqual(codes[4:], ["READY_FOR_POINTER_CLICK", "ALREADY_SUBMITTED"], key)

    def test_result_page_must_match_target(self):
        expected = {"failure": "FAILURE_SHOWN", "ambiguous": "SUCCESS_NOT_VERIFIED",
                    "wrong_slot": "SUCCESS_NOT_VERIFIED"}
        for key in REGISTRY.keys:
            for variant, code in expected.items():
                self.assertEqual(self.codes(f"{key}:result_{variant}")[-1], code,
                                 f"{key}/{variant}")

    def test_foreign_host_is_refused(self):
        for key in REGISTRY.keys:
            self.assertEqual(self.codes(f"{key}:wrong_host"), ["WRONG_HOST"], key)

    def test_lobby_entry_clicks_only_the_exact_room_label(self):
        for key, profile in REGISTRY.rooms.items():
            if profile.entry_label is None:
                # Unknown lobby category: never guess a tile, open it by hand.
                for case in ("entry", "entry_dup"):
                    self.assertEqual(self.codes(f"{key}:{case}"),
                                     ["ENTRY_MANUAL_REQUIRED", None], key)
                continue
            self.assertEqual(self.codes(f"{key}:entry"),
                             ["STATUS_ROOM_OPENED", profile.entry_label], key)
            self.assertEqual(self.codes(f"{key}:entry_dup"),
                             ["STATUS_ROOM_NOT_UNIQUE", None], key)


class SameFlowDifferentialTests(unittest.TestCase):
    """Rooms sharing a flow must run byte-identical engine code (no browser needed)."""

    def payload(self, script):
        prefix, suffix = app.ACTION_JS.split("__TASK__")
        self.assertTrue(script.startswith(prefix) and script.endswith(suffix))
        return json.loads(script[len(prefix):len(script) - len(suffix)])

    def test_engine_template_is_identical_for_all_rooms_and_phases(self):
        for key, profile in REGISTRY.rooms.items():
            for phase in app.PHASES:
                self.payload(app.action_script(phase, DAY, slot_for(profile), key))

    def test_same_flow_rooms_differ_only_in_identity_fields(self):
        identity = {"room", "mode", "slot"}
        profile_identity = {"key", "entryLabel", "tileKind", "tileValue",
                            "summaryTextAll", "summaryRegexAll"}
        for flow, members in REGISTRY.by_flow().items():
            if len(members) < 2:
                continue
            base = members[0]
            first = self.payload(app.action_script("slot", DAY, base.slots[0], base.key))
            for other in members[1:]:
                second = self.payload(app.action_script("slot", DAY, other.slots[0], other.key))
                self.assertEqual(set(first), set(second), flow)
                for field in set(first) - identity - {"profile"}:
                    self.assertEqual(first[field], second[field], (flow, field))
                for field in set(first["profile"]) - profile_identity:
                    self.assertEqual(first["profile"][field],
                                     second["profile"][field], (flow, field))

    def test_flow_behaviour_fields_come_from_the_flow_not_the_room(self):
        for profile in REGISTRY.rooms.values():
            task = profile.task_profile()
            self.assertEqual(task["slotSelector"], profile.flow.slot_selector)
            self.assertEqual(task["slotRequiresBook"], profile.flow.slot_requires_book_class)
            self.assertEqual(task["bookMarksSelected"], profile.flow.book_class_marks_selected)

    def test_unknown_room_or_foreign_slot_is_rejected(self):
        with self.assertRaises(ValueError):
            app.action_script("slot", DAY, "13:00-14:00", "no_such_room")
        for profile in REGISTRY.rooms.values():
            with self.assertRaises(ValueError):
                app.action_script("slot", DAY, "03:00-04:00", profile.key)


if __name__ == "__main__":
    unittest.main()
