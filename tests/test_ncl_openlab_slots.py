"""Offline checks: choose only a time-slot candidate, never seats/bookings."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ncl_openlab_slots import parse_slot_priority, plan_time_slots


def node(sample, disabled=False):
    return {"tag": "button", "sample": sample, "disabled": disabled,
            "clickable": True, "selected": False}


def snapshot():
    return {"host": "spms.ncl.edu.tw", "results": {
        "11/11": [node("11/11")],
        "音樂創作室": [node("音樂創作室")],
        "09:00-12:00": [node("09:00-12:00")],
        "13:00-16:00": [node("13:00-16:00")],
        "17:00-20:00": [node("17:00-20:00")],
    }}


class SlotTests(unittest.TestCase):
    def test_default_priority(self):
        self.assertEqual(parse_slot_priority(), (
            "09:00-12:00", "13:00-16:00", "17:00-20:00"))

    def test_user_custom_order(self):
        self.assertEqual(parse_slot_priority("17:00-20:00,09:00-12:00"),
                         ("17:00-20:00", "09:00-12:00"))

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            parse_slot_priority("09:00-12:00,09:00-12:00")

    def test_invalid_time_rejected(self):
        with self.assertRaises(ValueError):
            parse_slot_priority("10:00-11:00")

    def test_disabled_first_skips_to_next_observed(self):
        data = snapshot()
        data["results"]["17:00-20:00"][0]["disabled"] = True
        plan = plan_time_slots(data, date(2026, 11, 11),
                               ("17:00-20:00", "13:00-16:00"))
        self.assertEqual(plan["first_observed"], "13:00-16:00")
        self.assertFalse(plan["can_select_time"])

    def test_available_looking_time_is_still_unverified(self):
        plan = plan_time_slots(snapshot(), date(2026, 11, 11), ["09:00-12:00"])
        self.assertEqual(plan["status"], "OBSERVED_NOT_VERIFIED")
        self.assertFalse(plan["availability_verified"])
        self.assertFalse(plan["can_submit"])

    def test_wrong_room_fails_closed(self):
        data = snapshot()
        data["results"].pop("音樂創作室")
        plan = plan_time_slots(data, date(2026, 11, 11))
        self.assertIsNone(plan["first_observed"])
        self.assertEqual(plan["status"], "BLOCKED")

    def test_ambiguous_time_skipped(self):
        data = snapshot()
        data["results"]["09:00-12:00"].append(node("09:00-12:00"))
        plan = plan_time_slots(data, date(2026, 11, 11),
                               ("09:00-12:00", "13:00-16:00"))
        self.assertEqual(plan["first_observed"], "13:00-16:00")
        self.assertEqual(plan["checks"]["09:00-12:00"]["reason"], "SLOT_AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
