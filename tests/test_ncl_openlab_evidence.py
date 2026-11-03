"""No-network/offline tests for NCL sanitized DOM evidence collection."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ncl_openlab_evidence import evidence_script, validate_evidence

SLOTS = ("09:00-12:00", "13:00-16:00", "17:00-20:00")


def snapshot():
    return {"host": "spms.ncl.edu.tw", "room_label_candidates": 1, "times": [
        {"slot": s, "count": 1, "truncated": False, "nodes": [
            {"tag": "span", "control_tag": "button", "role": None,
             "disabled_ui_hint": False, "aria_selected": False,
             "checked": False, "mixed_slot_context": False,
             "status_hints": ["可預約"]}
        ]} for s in SLOTS]}


class EvidenceTests(unittest.TestCase):
    def test_js_is_read_only(self):
        js = evidence_script()
        self.assertIn("音樂創作室", js)
        for forbidden in (".click(", ".submit(", "fetch(", "XMLHttpRequest",
                          "location.reload", "localStorage", "document.cookie",
                          ".dispatchEvent(", "outerHTML"):
            self.assertNotIn(forbidden, js)

    def test_whitelisted_output(self):
        data = snapshot()
        data["account"] = "private-account-123"
        data["times"][0]["nodes"][0]["password"] = "secret"
        output = validate_evidence(data)
        self.assertNotIn("account", str(output))
        self.assertNotIn("password", str(output))
        self.assertNotIn("private-account", str(output))

    def test_wrong_host_is_rejected(self):
        data = snapshot()
        data["host"] = "other.example"
        with self.assertRaises(ValueError):
            validate_evidence(data)

    def test_invalid_node_hint_is_rejected(self):
        data = snapshot()
        data["times"][0]["nodes"][0]["status_hints"] = ["張三"]
        with self.assertRaises(ValueError):
            validate_evidence(data)

    def test_missing_times_rejected(self):
        data = snapshot()
        data["times"].pop()
        with self.assertRaises(ValueError):
            validate_evidence(data)

    def test_duplicate_time_rejected(self):
        data = snapshot()
        data["times"][1]["slot"] = SLOTS[0]
        with self.assertRaises(ValueError):
            validate_evidence(data)

    def test_invalid_boolean_flag_rejected(self):
        data = snapshot()
        data["times"][0]["nodes"][0]["checked"] = "false"
        with self.assertRaises(ValueError):
            validate_evidence(data)

    def test_disallowed_slot_rejected(self):
        with self.assertRaises(ValueError):
            evidence_script(["10:00-11:00"])

    def test_no_availability_inference(self):
        out = validate_evidence(snapshot())
        self.assertNotIn("availability_verified", str(out))
        self.assertEqual(out["times"][0]["nodes"][0]["status_hints"], ["可預約"])


if __name__ == "__main__":
    unittest.main()
