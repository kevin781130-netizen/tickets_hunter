"""Read-only final-step diagnostics: no booking authority or private data."""
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ncl_openlab_checkout import (
    CTA_LABELS, SOURCE, assess_checkout, checkout_script,
)
from ncl_openlab_guard import NCL_HOST


def snapshot(*, context=True, final=True, disabled=False):
    rows = []
    for label in CTA_LABELS:
        count = 1 if final and label == "預約" else 0
        rows.append({"label": label, "count": count,
                     "disabled_count": count if disabled else 0})
    value = 1 if context else 0
    return {"host": NCL_HOST, "source": SOURCE,
            "selected": {"date_count": value, "room_count": value,
                         "slot_count": value}, "actions": rows}


class CheckoutTests(unittest.TestCase):
    def test_script_exact_expected_target_and_readonly(self):
        js = checkout_script(date(2026, 11, 11), "09:00-12:00")
        self.assertIn("11/11", js)
        self.assertIn("音樂創作室", js)
        self.assertIn(".time-box2.selected", js)
        self.assertIn('"預約"', js)
        self.assertIn(".date-box.selected", js)
        for forbidden in (".click(", ".submit(", "fetch(", "location.reload(",
                          "document.cookie", "localStorage", "sessionStorage"):
            self.assertNotIn(forbidden, js)

    def test_other_room_hour_slot_rejected(self):
        with self.assertRaises(ValueError):
            checkout_script(date(2026, 11, 11), "09:00-10:00")

    def test_datetime_not_accepted_as_date(self):
        with self.assertRaises(ValueError):
            checkout_script(datetime(2026, 11, 11, 9), "09:00-12:00")

    def test_valid_context_and_visible_cta_still_never_book(self):
        report = assess_checkout(snapshot())
        self.assertEqual(report["status"], "OBSERVED_ONLY")
        self.assertTrue(report["final_reservation_action_visible"])
        self.assertTrue(report["selected_target_verified"])
        self.assertFalse(report["booking_verified"])
        self.assertFalse(report["can_click"])
        self.assertFalse(report["can_submit"])

    def test_final_cta_on_reference_room_is_not_target_verified(self):
        report = assess_checkout(snapshot(context=False))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(report["final_reservation_action_visible"])
        self.assertFalse(report["selected_target_verified"])
        self.assertFalse(report["can_submit"])

    def test_no_final_cta_blocks(self):
        report = assess_checkout(snapshot(final=False))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["final_reservation_action_visible"])

    def test_disabled_final_cta_blocks(self):
        report = assess_checkout(snapshot(disabled=True))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["final_reservation_action_visible"])

    def test_wrong_host_blocks(self):
        data = snapshot()
        data["host"] = "ncl.edu.tw.evil.example"
        self.assertEqual(assess_checkout(data)["reason"], "INVALID_CHECKOUT_EVIDENCE")

    def test_wrong_source_blocks(self):
        data = snapshot()
        data["source"] = "ncl_structured_dom_v1"
        self.assertEqual(assess_checkout(data)["status"], "BLOCKED")

    def test_extra_action_label_rejected(self):
        data = snapshot()
        data["actions"][1]["label"] = "帳號"
        self.assertEqual(assess_checkout(data)["actions"], [])

    def test_negative_or_noninteger_counts_rejected(self):
        data = snapshot()
        data["actions"][1]["count"] = -1
        self.assertEqual(assess_checkout(data)["status"], "BLOCKED")
        data = snapshot()
        data["selected"]["date_count"] = True
        self.assertEqual(assess_checkout(data)["status"], "BLOCKED")

    def test_action_count_bounds_and_disabled_count_rejected(self):
        data = snapshot()
        data["actions"][1]["disabled_count"] = 2
        self.assertEqual(assess_checkout(data)["status"], "BLOCKED")
        data = snapshot()
        data["actions"][1]["count"] = 201
        self.assertEqual(assess_checkout(data)["status"], "BLOCKED")

    def test_never_echo_untrusted_text_or_personal_fields(self):
        data = snapshot()
        data["private_note"] = "not_for_output"
        data["actions"][1]["secret"] = "not_for_output"
        result = assess_checkout(data)
        self.assertNotIn("not_for_output", str(result))
        self.assertEqual(result["actions"][1],
                         {"label": "預約", "count": 1, "disabled_count": 0})


if __name__ == "__main__":
    unittest.main()
