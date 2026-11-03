"""Contract regression tests based on screenshots of NCL OPEN LAB real DOM.

Example from actual visible markup:
<div class="time-box disabled reserving" data-param1="09:00-10:00">...</div>
<div class="time-box" data-param1="12:00-13:00">...</div>
<div class="space-box1 selected">P01 ...</div>
<div class="time-box2 disabled reserving" data-param1="09:00-12:00" data-param3="false">...</div>
<div class="date-box selected" id="date7">11/11<br><span class="weekWords">(三,Wed)</span></div>
<div class="time-box book" data-param1="09:00-10:00" data-param3="true">09:00-10:00</div>  # P03 only

This suite does not visit the reservation site or infer remaining capacity.
"""
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from ncl_openlab_guard import assess_probe
from ncl_openlab_slots import plan_time_slots
from ncl_openlab_evidence import evidence_script, validate_evidence

spec = importlib.util.spec_from_file_location(
    "ncl_openlab_probe", SOURCE / "ncl_openlab_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
DAY = date(2026, 11, 11)
SLOTS = ("09:00-12:00", "13:00-16:00", "17:00-20:00")


def node(text, *, selected=False, disabled=False, clickable=True):
    return {"tag": "div", "sample": text, "selected": selected,
            "disabled": disabled, "clickable": clickable}


def selected_page():
    return {"host": "spms.ncl.edu.tw", "source": "ncl_structured_dom_v1",
            "results": {
                "11/11": [node("11/11", selected=True)],
                "音樂創作室": [node("音樂創作室", selected=True)],
                **{slot: [node(slot)] for slot in SLOTS},
            }}


class StructuredDomContractTests(unittest.TestCase):
    def test_uses_exact_timebox_attribute(self):
        js = probe.probe_script(DAY)
        self.assertIn(".time-box[data-param1]", js)
        self.assertIn(".time-box2[data-param1]", js)
        self.assertIn('classList.contains("time-box2")', js)
        self.assertIn('el.getAttribute("data-param1") === time', js)
        self.assertNotIn('querySelectorAll("*")', js)

    def test_room_matches_space_tile_not_sidebar_heading(self):
        js = probe.probe_script(DAY)
        self.assertIn('querySelectorAll(".space-box1")', js)

    def test_selected_class_used(self):
        js = probe.probe_script(DAY)
        self.assertIn('classList.contains("selected")', js)

    def test_date_uses_real_date_box_not_nested_weekday_span(self):
        """NCL selected target date is div.date-box.selected, not a weekday span."""
        js = probe.probe_script(DAY)
        self.assertIn('querySelectorAll(".date-box")', js)
        self.assertIn('label.startsWith(dateLabel)', js)
        self.assertIn('isSelected(el)', js)
        self.assertNotIn('querySelectorAll("div, button, a")', js)
        self.assertNotIn('querySelectorAll(".date-box.selected")', js)

    def test_structured_date_must_be_selected(self):
        data = selected_page()
        data["results"]["11/11"][0]["selected"] = False
        self.assertEqual(assess_probe(data, DAY, SLOTS[0])["reason"], "DATE_NOT_SELECTED")

    def test_structured_room_must_be_selected(self):
        data = selected_page()
        data["results"]["音樂創作室"][0]["selected"] = False
        self.assertEqual(assess_probe(data, DAY, SLOTS[0])["reason"], "ROOM_NOT_SELECTED")

    def test_duplicate_space_tiles_block(self):
        data = selected_page()
        data["results"]["音樂創作室"].append(node("音樂創作室", selected=True))
        self.assertEqual(assess_probe(data, DAY, SLOTS[0])["reason"], "ROOM_AMBIGUOUS")

    def test_disabled_reserving_must_not_be_observed_candidate(self):
        data = selected_page()
        data["results"][SLOTS[0]][0]["disabled"] = True
        report = plan_time_slots(data, DAY, [SLOTS[0]])
        self.assertEqual(report["checks"][SLOTS[0]]["reason"], "SLOT_DISABLED_OR_UNKNOWN")
        self.assertEqual(report["time_states"][SLOTS[0]]["state"], "DISABLED_UI_HINT")
        self.assertFalse(report["can_submit"])

    def test_enabled_time_still_not_verified_availability(self):
        report = plan_time_slots(selected_page(), DAY, [SLOTS[0]])
        self.assertEqual(report["status"], "OBSERVED_NOT_VERIFIED")
        self.assertFalse(report["availability_verified"])
        self.assertFalse(report["can_select_time"])

    def test_evidence_scan_exact_class_based(self):
        js = evidence_script()
        self.assertIn('querySelectorAll(".time-box[data-param1], .time-box2[data-param1]")', js)
        self.assertIn('classList.contains(c)', js)
        self.assertNotIn("document.cookie", js)

    def test_music_room_time_box2_is_detected_without_booking(self):
        """Based on the actual three blocked 3-hour music-room slots."""
        probe_js = probe.probe_script(DAY)
        evidence_js = evidence_script()
        for script in (probe_js, evidence_js):
            self.assertIn(".time-box2[data-param1]", script)
            for forbidden in (".click(", ".submit(", "fetch(", "location.reload"):
                self.assertNotIn(forbidden, script)
        page = selected_page()
        for slot in SLOTS:
            page["results"][slot][0]["disabled"] = True
        report = plan_time_slots(page, DAY, SLOTS)
        self.assertIsNone(report["first_observed"])
        self.assertTrue(all(report["checks"][s]["reason"] == "SLOT_DISABLED_OR_UNKNOWN"
                            for s in SLOTS))
        self.assertFalse(report["can_select_time"])
        self.assertFalse(report["can_submit"])

    def test_music_room_css_hints_allowlisted_and_private_values_rejected(self):
        """Read CSS class only; data-param2/3 are never availability proof."""
        sample = {"host": "spms.ncl.edu.tw", "room_label_candidates": 1,
                  "times": []}
        for slot in SLOTS:
            sample["times"].append({
                "slot": slot, "count": 1, "truncated": False,
                "nodes": [{"tag": "div", "control_tag": "div", "role": None,
                           "disabled_ui_hint": True, "aria_selected": False,
                           "checked": False, "mixed_slot_context": False,
                           "status_hints": [],
                           "class_hints": ["time-box2", "disabled", "reserving"],
                           "data-param2": "216", "data-param3": "false"}]})
        cleaned = validate_evidence(sample)
        for slot_data in cleaned["times"]:
            row = slot_data["nodes"][0]
            self.assertEqual(row["class_hints"], ["disabled", "reserving", "time-box2"])
            self.assertNotIn("data-param2", row)
            self.assertNotIn("data-param3", row)
        self.assertNotIn("availability_verified", str(cleaned))

    def test_book_class_is_sanitized_only_not_verified_availability(self):
        """The real P03 hour-long .time-box.book is reference, not music-room proof."""
        js = evidence_script()
        self.assertIn('"book"', js)
        self.assertNotIn('data-param3', js)
        with self.assertRaises(ValueError):
            evidence_script(("09:00-10:00",))  # P03 is not a music-room slot
        data = {"host": "spms.ncl.edu.tw", "room_label_candidates": 1,
                "times": []}
        for slot in SLOTS:
            data["times"].append({
                "slot": slot, "count": 1, "truncated": False,
                "nodes": [{"tag": "div", "control_tag": "div", "role": None,
                           "disabled_ui_hint": False, "aria_selected": False,
                           "checked": False, "mixed_slot_context": False,
                           "status_hints": [],
                           "class_hints": ["time-box2", "book"],
                           "data-param3": "true"}]})
        clean = validate_evidence(data)
        for row in clean["times"]:
            self.assertEqual(row["nodes"][0]["class_hints"], ["book", "time-box2"])
            self.assertNotIn("data-param3", row["nodes"][0])
        # Even if a genuine music-room slot later appears enabled,
        # a read-only candidate must never authorize automatic booking.
        report = plan_time_slots(selected_page(), DAY, SLOTS)
        self.assertFalse(report["availability_verified"])
        self.assertFalse(report["can_select_time"])
        self.assertFalse(report["can_submit"])

    def test_book_cannot_override_disabled_reserving(self):
        """Even contradictory UI hints never allow selection of a disabled slot."""
        page = selected_page()
        for slot in SLOTS:
            page["results"][slot][0]["disabled"] = True
        report = plan_time_slots(page, DAY, SLOTS)
        for slot in SLOTS:
            self.assertEqual(report["checks"][slot]["reason"],
                             "SLOT_DISABLED_OR_UNKNOWN")
            self.assertEqual(report["time_states"][slot]["state"],
                             "DISABLED_UI_HINT")
        self.assertIsNone(report["first_observed"])
        self.assertFalse(report["can_select_time"])
        self.assertFalse(report["can_submit"])
        # Diagnostics may preserve both class tokens but must not assert vacancy.
        data = {"host": "spms.ncl.edu.tw", "room_label_candidates": 1,
                "times": []}
        for slot in SLOTS:
            data["times"].append({
                "slot": slot, "count": 1, "truncated": False,
                "nodes": [{"tag": "div", "control_tag": "div", "role": None,
                           "disabled_ui_hint": True, "aria_selected": False,
                           "checked": False, "mixed_slot_context": False,
                           "status_hints": [],
                           "class_hints": ["time-box2", "book", "disabled",
                                           "reserving"]}]})
        clean = validate_evidence(data)
        self.assertEqual(clean["times"][0]["nodes"][0]["class_hints"],
                         ["book", "disabled", "reserving", "time-box2"])
        self.assertTrue(clean["times"][0]["nodes"][0]["disabled_ui_hint"])

    def test_evidence_allows_only_status_class_hints(self):
        data = {"host": "spms.ncl.edu.tw", "room_label_candidates": 1,
                "times": []}
        for slot in SLOTS:
            data["times"].append({
                "slot": slot, "count": 1, "truncated": False,
                "nodes": [{"tag": "div", "control_tag": "div",
                           "role": None, "disabled_ui_hint": True,
                           "aria_selected": False, "checked": False,
                           "mixed_slot_context": False, "status_hints": [],
                           "class_hints": ["time-box", "disabled", "reserving"]}]})
        clean = validate_evidence(data)
        self.assertEqual(clean["times"][0]["nodes"][0]["class_hints"],
                         ["disabled", "reserving", "time-box"])
        data["times"][0]["nodes"][0]["class_hints"].append("user-sensitive")
        with self.assertRaises(ValueError):
            validate_evidence(data)


if __name__ == "__main__":
    unittest.main()
