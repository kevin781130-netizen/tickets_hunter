"""Offline tests for non-booking, allowlisted date/room DOM diagnostics."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ncl_openlab_date_diag import diagnostic_script, validate_diagnostic

DAY = date(2026, 11, 11)


def data():
    return {
        "host": "spms.ncl.edu.tw", "status": "READ_ONLY",
        "expected_date": "11/11", "date_grid_total": 7,
        "date_match_count": 1, "room_grid_total": 3,
        "p03_match_count": 1,
        "date_flags": [{
            "class_flags": ["book"], "parent_class_flags": [],
            "aria_selected": False, "aria_pressed": False,
            "data_selected": False, "visible": True,
            "private": "should-not-leak"}],
        "p03_flags": [{
            "class_flags": ["selected"], "parent_class_flags": [],
            "aria_selected": False, "aria_pressed": False,
            "data_selected": False, "visible": True,
        }],
        "password": "never-write-me",
    }


class SelectionDiagnosticsTests(unittest.TestCase):
    def test_read_only_dom_and_explicit_date(self):
        script = diagnostic_script(DAY)
        self.assertIn("11/11", script)
        self.assertIn('^P03(?:\\s|$)', script)
        for forbidden in (".click(", ".submit(", "fetch(", "XMLHttpRequest",
                          "location.reload", "document.cookie", "outerHTML",
                          "localStorage"):
            self.assertNotIn(forbidden, script)

    def test_sanitized_output_never_emits_private_content(self):
        result = validate_diagnostic(data(), DAY)
        self.assertEqual(result["date_flags"][0]["class_flags"], ["book"])
        self.assertNotIn("private", str(result))
        self.assertNotIn("password", str(result))
        self.assertNotIn("should-not-leak", str(result))

    def test_fail_closed_wrong_host_and_incorrect_date(self):
        bad = data()
        bad["host"] = "example.net"
        with self.assertRaises(ValueError):
            validate_diagnostic(bad, DAY)
        bad = data()
        bad["expected_date"] = "11/12"
        with self.assertRaises(ValueError):
            validate_diagnostic(bad, DAY)

    def test_invalid_or_non_allowlisted_flags_are_rejected(self):
        bad = data()
        bad["date_flags"][0]["class_flags"] = ["secret-token-value"]
        with self.assertRaises(ValueError):
            validate_diagnostic(bad, DAY)
        bad = data()
        bad["date_flags"][0]["aria_selected"] = "true"
        with self.assertRaises(ValueError):
            validate_diagnostic(bad, DAY)

    def test_no_date_tile_is_reported_without_guess(self):
        bad = data()
        bad["date_match_count"] = 0
        bad["date_flags"] = []
        result = validate_diagnostic(bad, DAY)
        self.assertEqual(result["date_match_count"], 0)
        self.assertEqual(result["date_flags"], [])


if __name__ == "__main__":
    unittest.main()
