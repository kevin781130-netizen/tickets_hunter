"""Read-only, privacy-bounded OPEN LAB room DOM discovery tests."""
import copy
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import ncl_openlab_room_diag as diag


def sample():
    return {
        "status": "READ_ONLY",
        "date_tile_count": 7,
        "selected_date_count": 1,
        "room_tile_count": 3,
        "rooms": [
            {"code": "P03", "kind": "space-box1",
             "selected": True, "book": False, "disabled": False},
        ],
        "time_tile_count": 11,
        "slots": [
            {"slot": "17:00-18:00", "kind": "time-box",
             "selected": False, "book": True, "disabled": False},
        ],
        "note": "DOM_STATES_ONLY_NOT_AVAILABILITY",
    }


class RoomReadOnlyDiagnosticsTests(unittest.TestCase):
    def test_js_does_not_click_submit_reload_or_read_identity(self):
        js = diag.ROOM_DIAG_JS
        for forbidden in (
            ".click(", "fetch(", "XMLHttpRequest", "location.reload(",
            "document.cookie", "localStorage", "sessionStorage",
            "innerHTML", "document.body.innerText", "data-param2",
            "data-param3", "window.location.href =",
        ):
            self.assertNotIn(forbidden, js)
        self.assertIn('location.hostname !== "spms.ncl.edu.tw"', js)
        self.assertIn('DOM_STATES_ONLY_NOT_AVAILABILITY', js)

    def test_valid_sanitized_room_and_slot_flags_are_accepted(self):
        self.assertEqual(diag.validate_report(sample()), sample())

    def test_rejects_arbitrary_room_identifiers_or_private_fields(self):
        for bad in ("Member Name", "account_123456", "<img>"):
            item = sample()
            item["rooms"][0]["code"] = bad
            self.assertEqual(
                diag.validate_report(item)["status"], "INVALID_RESULT")
        item = sample()
        item["rooms"][0]["user_name"] = "do not include this"
        self.assertEqual(
            diag.validate_report(item)["status"], "INVALID_RESULT")

    def test_rejects_invalid_time_or_nonboolean_selection_flags(self):
        item = sample()
        item["slots"][0]["slot"] = "booking-123456"
        self.assertEqual(diag.validate_report(item)["status"], "INVALID_RESULT")
        item = sample()
        item["slots"][0]["book"] = "true"
        self.assertEqual(diag.validate_report(item)["status"], "INVALID_RESULT")

    def test_wrong_host_and_unexpected_result_fail_closed(self):
        for value in (None, [], {"status": "WRONG_HOST"},
                      {"status": "READ_ONLY", "rooms": []}):
            self.assertNotEqual(
                diag.validate_report(value).get("status"), "READ_ONLY")


if __name__ == "__main__":
    unittest.main()
