"""Offline fail-closed tests for NCL room/time matching."""
import importlib.util
from datetime import date
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "src" / "ncl_openlab_guard.py"
SPEC = importlib.util.spec_from_file_location("ncl_openlab_guard", PATH)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def candidate(text, *, disabled=False, clickable=True, selected=False):
    return {"tag": "button", "sample": text, "disabled": disabled,
            "clickable": clickable, "selected": selected}


def example():
    return {"host": "spms.ncl.edu.tw", "results": {
        "11/11": [candidate("11/11")],
        "音樂創作室": [candidate("音樂創作室")],
        "09:00-12:00": [candidate("09:00-12:00")],
    }}


class NclGuardTests(unittest.TestCase):
    def assess(self, snapshot):
        return guard.assess_probe(snapshot, date(2026, 11, 11), "09:00-12:00")

    def test_unique_usable_candidates_still_never_book(self):
        outcome = self.assess(example())
        self.assertEqual(outcome["status"], "OBSERVED_ONLY")
        self.assertFalse(outcome["can_book"])
        self.assertFalse(outcome["can_click"])

    def test_missing_room_fails_closed(self):
        data = example()
        del data["results"]["音樂創作室"]
        self.assertEqual(self.assess(data)["reason"], "ROOM_NOT_FOUND")

    def test_duplicate_room_fails_closed(self):
        data = example()
        data["results"]["音樂創作室"].append(candidate("音樂創作室"))
        self.assertEqual(self.assess(data)["reason"], "ROOM_AMBIGUOUS")

    def test_disabled_slot_fails_closed(self):
        data = example()
        data["results"]["09:00-12:00"][0]["disabled"] = True
        self.assertEqual(self.assess(data)["reason"], "SLOT_DISABLED_OR_UNKNOWN")

    def test_unverified_disabled_state_fails_closed(self):
        data = example()
        del data["results"]["09:00-12:00"][0]["disabled"]
        self.assertEqual(self.assess(data)["reason"], "SLOT_DISABLED_OR_UNKNOWN")

    def test_wrong_host_fails_closed(self):
        data = example()
        data["host"] = "example.com"
        self.assertEqual(self.assess(data)["reason"], "HOST_MISMATCH")

    def test_noninteractive_slot_fails_closed(self):
        data = example()
        data["results"]["09:00-12:00"][0]["clickable"] = False
        self.assertEqual(self.assess(data)["reason"], "SLOT_NOT_ACTIONABLE")

    def test_different_room_text_fails_closed(self):
        data = example()
        data["results"]["音樂創作室"][0]["sample"] = "個人直播室"
        self.assertEqual(self.assess(data)["reason"], "ROOM_TEXT_MISMATCH")

    def test_invalid_time_fails_closed(self):
        data = example()
        result = guard.assess_probe(data, date(2026, 11, 11), "10:00-11:00")
        self.assertEqual(result["reason"], "INVALID_SLOT")

    def test_selected_but_noninteractive_is_only_observed(self):
        data = example()
        data["results"]["音樂創作室"][0]["clickable"] = False
        data["results"]["音樂創作室"][0]["selected"] = True
        self.assertEqual(self.assess(data)["status"], "OBSERVED_ONLY")


if __name__ == "__main__":
    unittest.main()
