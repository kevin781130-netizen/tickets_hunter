"""Offline invariants for the full NCL OPEN LAB catalog.

The user can see all official room categories, but unknown room/slot DOM
contracts cannot be converted into live reservation submissions.
"""
import sys
import unittest
from datetime import date
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from ncl_openlab_picker_model import available_slots, build_booking_args, ROOM_CHOICES
from ncl_openlab_room_catalog import (
    ROOM_CATALOG, ROOM_GROUPS, OFFICIAL_OVERVIEW_URL, room_notice, room_status,
)

DAY = date(2026, 11, 12)


class OpenLabCatalogTests(unittest.TestCase):
    def test_all_official_categories_accounted_for_without_duplicate_mode(self):
        self.assertEqual(len(ROOM_CATALOG), 14)
        self.assertEqual(len(ROOM_CHOICES), 14)
        self.assertEqual(len(set(ROOM_CHOICES.values())), 14)
        expected_labels = (
            "討論室", "團練室", "星際直播攝影棚", "親子直播室",
            "音樂創作室", "個人直播室", "創藝手作坊縫紉機",
            "動漫創作坊電腦", "雷神工作室", "影印掃描用電腦",
            "創藝手作坊電腦", "數位科技實作區電腦",
            "影音欣賞區", "語言學習區",
        )
        for label in expected_labels:
            self.assertEqual(sum(label in x for x in ROOM_CHOICES.values()), 1)
        self.assertEqual(
            OFFICIAL_OVERVIEW_URL,
            "https://spms.ncl.edu.tw/NLT/co/multimedia.jsp?page=media",
        )

    def test_status_groups_are_exhaustive_and_nonoverlapping(self):
        flat = [key for _, modes in ROOM_GROUPS for key in modes]
        self.assertEqual(len(flat), len(set(flat)))
        self.assertEqual(set(flat), set(ROOM_CATALOG))
        self.assertEqual(
            {key for key, spec in ROOM_CATALOG.items() if spec.channel == "online"},
            {key for key, spec in ROOM_CATALOG.items() if spec.automation != "onsite_only"},
        )
        self.assertEqual(sum(x.channel == "online" for x in ROOM_CATALOG.values()), 12)
        self.assertEqual(sum(x.channel == "onsite_only" for x in ROOM_CATALOG.values()), 2)

    def test_only_two_verified_backends_have_selectable_time_slots(self):
        verified = {key for key in ROOM_CATALOG if room_status(key) == "verified"}
        self.assertEqual(verified, {"music", "p03"})
        self.assertEqual(len(available_slots("music")), 3)
        self.assertEqual(len(available_slots("p03")), 11)
        for key in ROOM_CATALOG:
            if key not in verified:
                self.assertEqual(available_slots(key), ())
        for unknown in ("", "P04", "anything"):
            with self.assertRaises(ValueError):
                available_slots(unknown)

    def test_unverified_online_rooms_are_hard_blocked_from_real_booking(self):
        for key, spec in ROOM_CATALOG.items():
            if spec.automation != "needs_live_dom":
                continue
            with self.subTest(key=key), self.assertRaisesRegex(
                ValueError, "尚未實機驗證"
            ):
                build_booking_args(
                    day=DAY, room=key, slots=["09:00-12:00"],
                    auto_submit=True, immediate=True, accept_terms=True,
                    fallback_any_slot=True)
            self.assertIn("禁止自動送出", room_notice(key))

    def test_onsite_spaces_are_hard_blocked_even_with_submit_permission(self):
        for key, spec in ROOM_CATALOG.items():
            if spec.channel != "onsite_only":
                continue
            with self.subTest(key=key), self.assertRaisesRegex(
                ValueError, "僅供現場借用"
            ):
                build_booking_args(
                    day=DAY, room=key, slots=["09:00-12:00"],
                    auto_submit=True, immediate=True, accept_terms=True,
                    fallback_any_slot=True)

    def test_existing_verified_room_booking_argv_remains_unchanged(self):
        for key, slot in (
            ("music", "13:00-16:00"), ("p03", "17:00-18:00")
        ):
            with self.subTest(key=key):
                argv = build_booking_args(
                    day=DAY, room=key, slots=[slot],
                    auto_submit=True, immediate=True)
                self.assertEqual(argv[1], key)
                self.assertIn("--auto-submit", argv)
                self.assertNotIn("--reserve-two", argv)

    def test_gui_uses_grouped_two_column_layout_and_room_specific_note(self):
        gui = (SRC / "ncl_openlab_picker.py").read_text(encoding="utf-8")
        self.assertIn("for group_title, modes in ROOM_GROUPS:", gui)
        self.assertIn("choice.grid(row=index // 2 + 1, column=index % 2", gui)
        self.assertIn('choice.configure(state="disabled")', gui)
        self.assertIn("room_notice(room)", gui)
        self.assertIn('status != "verified"', gui)


if __name__ == "__main__":
    unittest.main()
