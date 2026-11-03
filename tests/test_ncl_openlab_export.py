"""Offline tests for the sanitized opt-in evidence exporter."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ncl_openlab_export import EVIDENCE_FILENAME, make_capture, save_capture


def page():
    slots = ("09:00-12:00", "13:00-16:00", "17:00-20:00")
    return {"host": "spms.ncl.edu.tw", "room_label_candidates": 1,
            "account": "PRIVATE_ACCOUNT_MARKER",
            "times": [{"slot": s, "count": 1, "truncated": False,
                       "nodes": [{"tag": "span", "control_tag": "button",
                                  "role": None, "disabled_ui_hint": False,
                                  "aria_selected": False, "checked": False,
                                  "mixed_slot_context": False,
                                  "status_hints": ["額滿"],
                                  "cookie": "PRIVATE_COOKIE_MARKER"}]} for s in slots]}


class EvidenceExportTests(unittest.TestCase):
    def test_only_safe_fields_are_exported(self):
        capture = make_capture(page(), date(2026, 11, 11), ["13:00-16:00"])
        with tempfile.TemporaryDirectory() as directory:
            path = save_capture(directory, capture)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_", text)
            self.assertEqual(path.name, EVIDENCE_FILENAME)
            self.assertFalse(json.loads(text)["availability_verified"])
            self.assertEqual(json.loads(text)["priorities"], ["13:00-16:00"])

    def test_does_not_overwrite_existing_capture(self):
        capture = make_capture(page(), date(2026, 11, 11), None)
        with tempfile.TemporaryDirectory() as directory:
            path = save_capture(directory, capture)
            with self.assertRaises(FileExistsError):
                save_capture(directory, capture)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 1)

    def test_invalid_origin_is_rejected(self):
        value = page()
        value["host"] = "other.example"
        with self.assertRaises(ValueError):
            make_capture(value, date(2026, 11, 11), None)

    def test_datetime_target_is_rejected(self):
        from datetime import datetime
        with self.assertRaises(ValueError):
            make_capture(page(), datetime(2026, 11, 11), None)

    def test_export_revalidates_injected_payload(self):
        capture = make_capture(page(), date(2026, 11, 11), None)
        capture["evidence"]["times"][0]["slot"] = "not a time"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                save_capture(directory, capture)
            self.assertFalse((Path(directory) / EVIDENCE_FILENAME).exists())

    def test_export_does_not_persist_extra_capture_fields(self):
        capture = make_capture(page(), date(2026, 11, 11), None)
        capture["credential"] = "PRIVATE_CREDENTIAL_MARKER"
        with tempfile.TemporaryDirectory() as directory:
            result = save_capture(directory, capture).read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_", result)
            self.assertEqual(json.loads(result)["status"], "UNVERIFIED_DOM_ONLY")


if __name__ == "__main__":
    unittest.main()
