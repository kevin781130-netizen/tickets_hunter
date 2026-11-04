"""Offline tests for non-booking, allowlisted date/room DOM diagnostics."""
import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ncl_openlab_date_diag import (
    collect_browser_diagnostics, diagnostic_script, validate_diagnostic,
)

DAY = date(2026, 11, 11)


def data():
    return {
        "host": "spms.ncl.edu.tw", "status": "READ_ONLY",
        "expected_date": "11/11", "iframe_count": 0,
        "date_grid_total": 7,
        "date_match_count": 1, "room_grid_total": 3,
        "room_class_counts": {"space-box1": 1, "space-box2": 1, "space-box3": 1},
        "room_code_counts": {"P01": 1, "P02": 1, "P03": 1},
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


class MultiTabDiagnosticsTests(unittest.TestCase):
    def test_scan_actual_ncl_booking_tab_not_only_initial_page(self):
        landing = data()
        landing.update({
            "iframe_count": 0, "date_grid_total": 0, "date_match_count": 0,
            "date_flags": [], "room_grid_total": 0, "p03_match_count": 0,
            "room_class_counts": {"space-box1": 0, "space-box2": 0, "space-box3": 0},
            "room_code_counts": {"P01": 0, "P02": 0, "P03": 0},
            "p03_flags": [],
        })
        outside = SimpleNamespace(
            target=SimpleNamespace(url="https://example.org/"),
            evaluate=AsyncMock(side_effect=AssertionError(
                "never inspect tabs outside official NCL host")))
        homepage = SimpleNamespace(
            target=SimpleNamespace(url="https://spms.ncl.edu.tw/"),
            evaluate=AsyncMock(return_value=landing))
        booking = SimpleNamespace(
            target=SimpleNamespace(
                url="https://spms.ncl.edu.tw/NLT/co/media_discussion.jsp"),
            evaluate=AsyncMock(return_value=data()))
        browser = SimpleNamespace(
            tabs=[homepage, outside, booking], update_targets=AsyncMock())
        result = asyncio.run(collect_browser_diagnostics(browser, DAY))
        browser.update_targets.assert_awaited_once()
        outside.evaluate.assert_not_awaited()
        homepage.evaluate.assert_awaited_once()
        booking.evaluate.assert_awaited_once()
        self.assertTrue(result["date_grid_detected"])
        self.assertEqual(result["total_open_tabs"], 3)
        self.assertEqual(result["official_ncl_tabs"], 2)
        self.assertEqual(result["pages"][0]["page_kind"], "other_ncl_page")
        self.assertEqual(result["pages"][1]["tab_index"], 2)
        self.assertEqual(result["pages"][1]["page_kind"], "booking")
        self.assertEqual(result["pages"][1]["date_match_count"], 1)
        self.assertNotIn("example.org", str(result))

    def test_diagnostic_handles_no_official_tabs(self):
        browser = SimpleNamespace(
            tabs=[SimpleNamespace(
                target=SimpleNamespace(url="about:blank"),
                evaluate=AsyncMock())],
            update_targets=AsyncMock())
        result = asyncio.run(collect_browser_diagnostics(browser, DAY))
        self.assertEqual(result["official_ncl_tabs"], 0)
        self.assertFalse(result["date_grid_detected"])

    def test_closed_tab_is_reported_without_raw_errors(self):
        page = SimpleNamespace(
            target=SimpleNamespace(
                url="https://spms.ncl.edu.tw/NLT/co/media_discussion.jsp"),
            evaluate=AsyncMock(side_effect=RuntimeError("private-value")))
        browser = SimpleNamespace(tabs=[page], update_targets=AsyncMock())
        result = asyncio.run(collect_browser_diagnostics(browser, DAY))
        self.assertFalse(result["date_grid_detected"])
        self.assertEqual(result["pages"][0]["status"], "READ_FAILED")
        self.assertNotIn("private-value", str(result))

    def test_room_candidates_are_only_allowlisted_css_classes_and_codes(self):
        result = validate_diagnostic(data(), DAY)
        self.assertEqual(result["room_class_counts"]["space-box3"], 1)
        self.assertEqual(result["room_code_counts"]["P03"], 1)
        js = diagnostic_script(DAY)
        self.assertIn('".space-box1, .space-box2, .space-box3"', js)
        self.assertIn('roomCodes.map(code', js)

    def test_invalid_room_class_counts_fail_closed(self):
        item = data()
        item["room_class_counts"]["space-box3"] = "private-payload"
        with self.assertRaises(ValueError):
            validate_diagnostic(item, DAY)
        item = data()
        item["room_code_counts"]["P04"] = 1
        with self.assertRaises(ValueError):
            validate_diagnostic(item, DAY)

    def test_iframe_count_is_only_allowlisted_number(self):
        info = data()
        info["iframe_count"] = 2
        result = validate_diagnostic(info, DAY)
        self.assertEqual(result["iframe_count"], 2)
        info["iframe_count"] = "secret"
        with self.assertRaises(ValueError):
            validate_diagnostic(info, DAY)


if __name__ == "__main__":
    unittest.main()
