"""Read-only time-status tests, independent of live NCL website."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ncl_openlab_status import classify_time_state

SLOT = "09:00-12:00"


def snapshot(disabled=False):
    return {"results": {SLOT: [{"sample": SLOT, "disabled": disabled}]}}


def blocked(reason):
    return {"status": "BLOCKED", "reason": reason}


class StatusTests(unittest.TestCase):
    def test_observed_is_not_availability(self):
        value = classify_time_state(snapshot(), SLOT, {"status": "OBSERVED_ONLY"})
        self.assertEqual(value["state"], "CANDIDATE_UNVERIFIED")
        self.assertFalse(value["availability_verified"])
        self.assertFalse(value["can_book"])

    def test_explicit_disabled_control(self):
        value = classify_time_state(snapshot(True), SLOT, blocked("SLOT_DISABLED_OR_UNKNOWN"))
        self.assertEqual(value["state"], "CONTROL_DISABLED")
        self.assertFalse(value["can_book"])

    def test_disabled_not_equal_full(self):
        value = classify_time_state(snapshot(True), SLOT, blocked("SLOT_DISABLED_OR_UNKNOWN"))
        self.assertNotIn("FULL", value["state"])

    def test_disabled_state_unknown(self):
        value = classify_time_state(snapshot(False), SLOT, blocked("SLOT_DISABLED_OR_UNKNOWN"))
        self.assertEqual(value["state"], "UNKNOWN")

    def test_missing_slot(self):
        value = classify_time_state(snapshot(), SLOT, blocked("SLOT_NOT_FOUND"))
        self.assertEqual(value["state"], "NOT_DISPLAYED")

    def test_duplicate_slot(self):
        value = classify_time_state(snapshot(), SLOT, blocked("SLOT_AMBIGUOUS"))
        self.assertEqual(value["state"], "AMBIGUOUS")

    def test_room_missing_does_not_claim_slot_state(self):
        value = classify_time_state(snapshot(True), SLOT, blocked("ROOM_NOT_FOUND"))
        self.assertEqual(value["state"], "UNKNOWN")

    def test_wrong_host_fails_closed(self):
        value = classify_time_state(snapshot(True), SLOT, blocked("HOST_MISMATCH"))
        self.assertEqual(value["state"], "UNKNOWN")

    def test_invalid_snapshot_no_crash(self):
        value = classify_time_state(None, SLOT, blocked("SLOT_DISABLED_OR_UNKNOWN"))
        self.assertEqual(value["state"], "UNKNOWN")

    def test_invalid_assessment_no_crash(self):
        value = classify_time_state(snapshot(), SLOT, None)
        self.assertEqual(value["state"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
