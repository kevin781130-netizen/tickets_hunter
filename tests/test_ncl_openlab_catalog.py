"""Strict catalog and submission-gate regression tests; no network or browser."""
import ast
import contextlib
import copy
import io
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ncl_openlab_autobook as engine
import ncl_openlab_picker_model as picker
import ncl_openlab_rooms as rooms

RAW = json.loads(rooms.DEFAULT_CONFIG.read_text(encoding="utf-8"))


class FullCenterCatalogTests(unittest.TestCase):
    def test_14_categories_and_onsite_exclusions(self):
        registry = rooms.get_registry()
        self.assertEqual(len(registry.categories), 14)
        self.assertEqual(len(picker.CATEGORY_CHOICES), 14)
        onsite = [c for c in registry.categories if c.booking_mode == "ONSITE_ONLY"]
        self.assertEqual({c.label for c in onsite}, {"影音欣賞區", "語言學習區"})
        for c in onsite:
            self.assertEqual(picker.room_keys_for_category(c.key), ())
            self.assertIn("僅供現場借用", picker.category_notice(c.key))

    def test_every_known_unit_mapped_once_and_room_specific(self):
        registry = rooms.get_registry()
        mapped = [key for c in registry.categories for key in c.room_keys]
        self.assertEqual(len(mapped), 11)
        self.assertEqual(set(mapped), set(registry.keys))
        self.assertEqual(picker.room_keys_for_category("music"), ("music",))
        self.assertEqual(picker.room_keys_for_category("personal_stream"), ("p03",))
        self.assertEqual(len(picker.room_keys_for_category("sewing")), 9)
        self.assertEqual(picker.category_for_room("sewing08"), "sewing")
        self.assertEqual(picker.category_for_room("embroidery01"), "sewing")

    def test_unknown_room_categories_do_not_create_fake_units(self):
        self.assertEqual(picker.room_keys_for_category("rehearsal"), ())
        self.assertEqual(picker.room_keys_for_category("anime_pc"), ())
        self.assertIn("NOT_VERIFIED", picker.category_notice("rehearsal"))
        with self.assertRaises(ValueError):
            picker.room_keys_for_category("nonexistent")

    def test_only_observed_slot_rule_is_selectable(self):
        self.assertEqual(len(picker.selectable_slots("sewing01")), 11)
        for key in ("sewing02", "sewing03", "sewing04", "sewing05",
                    "sewing06", "sewing07", "sewing08", "embroidery01"):
            self.assertEqual(picker.selectable_slots(key), ())
            self.assertFalse(rooms.get_registry().room(key).slots_verified)
        self.assertEqual(picker.selectable_slots("music"),
                         ("09:00-12:00", "13:00-16:00", "17:00-20:00"))

    def test_only_p03_has_live_positive_booking_evidence(self):
        registry = rooms.get_registry()
        verified = [key for key, profile in registry.rooms.items()
                    if profile.live == "LIVE_VERIFIED"]
        self.assertEqual(verified, ["p03"])
        self.assertTrue(picker.room_is_verified("p03"))
        self.assertFalse(picker.room_is_verified("music"))

    def test_no_ack_can_unlock_unverified_submit(self):
        for key, slot in (("music", "13:00-16:00"),
                          ("sewing01", "13:00-14:00"),
                          ("sewing08", "13:00-14:00")):
            with self.subTest(room=key):
                with self.assertRaisesRegex(ValueError, "NOT_VERIFIED"):
                    picker.build_booking_args(day=date(2026, 11, 12), room=key,
                                              slots=[slot], auto_submit=True,
                                              ack_unverified=True)

    def test_verified_p03_preserves_single_submit_path(self):
        argv = picker.build_booking_args(day=date(2026, 11, 12), room="p03",
                                         slots=["13:00-14:00"], auto_submit=True)
        self.assertIn("--auto-submit", argv)
        self.assertNotIn("--ack-room-unverified", argv)

    def test_cli_rejects_submit_before_opening_any_browser(self):
        args = ["app", "--room", "music", "--date", "2026-11-12",
                "--slots", "13:00-16:00", "--auto-submit", "--ack-room-unverified"]
        err = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                engine.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("NOT_VERIFIED", err.getvalue())

    def test_invalid_catalog_is_fail_closed(self):
        for edit in (
            lambda d: d["categories"][5]["room_keys"].append("p03"),
            lambda d: d["categories"][0]["room_keys"].append("music"),
            lambda d: d["categories"][7]["room_keys"].append("music"),
            lambda d: d["categories"].pop(7),
        ):
            with self.subTest(edit=edit):
                config = copy.deepcopy(RAW)
                edit(config)
                with self.assertRaises(rooms.RoomConfigError):
                    rooms.parse_config(config)

    def test_tk_frontend_has_two_selectors_and_parses(self):
        source = (ROOT / "src" / "ncl_openlab_picker.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("self.category_box = ttk.Combobox", source)
        self.assertIn("self.room_box = ttk.Combobox", source)
        self.assertIn("room_keys_for_category(self.category.get())", source)
        self.assertIn("room_is_verified(self._room_key())", source)

    def test_guided_inventory_is_read_only_and_operator_labels_unverified(self):
        from ncl_openlab_inventory import INVENTORY_JS
        source = (ROOT / "src" / "ncl_openlab_inventory.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('parser.add_argument("--guided"', source)
        self.assertIn("OPERATOR_SELECTED_NOT_VERIFIED", source)
        for forbidden in (".click(", ".submit(", "fetch(", "location.reload",
                          "localStorage", "document.cookie"):
            self.assertNotIn(forbidden, INVENTORY_JS)


if __name__ == "__main__":
    unittest.main()
