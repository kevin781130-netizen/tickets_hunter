"""Inventory classification, config drafts, and the 'new room = config only' guarantee."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import ncl_browser as browser
import ncl_fixtures as fx
import ncl_openlab_inventory as inv
import ncl_openlab_rooms as rooms

REGISTRY = rooms.get_registry()
DAY = date(2026, 11, 11)


def snapshot(**over):
    base = {"host": "spms.ncl.edu.tw", "source": "ncl_inventory_v1",
            "path": "/NLT/co/media_discussion.jsp",
            "status_labels": [{"label": "音樂創作室", "disabled": False},
                              {"label": "個人直播室", "disabled": False},
                              {"label": "新空間", "disabled": False}],
            "dates": ["11/11", "11/12"],
            "rooms": [{"label": "P03 個人直播室", "selected": True, "disabled": False},
                      {"label": "P05 個人直播室", "selected": False, "disabled": False}],
            "slots": [{"label": "09:00-10:00", "kind": "time-box", "selected": False,
                       "book": False, "disabled": False},
                      {"label": "10:00-11:00", "kind": "time-box", "selected": False,
                       "book": False, "disabled": True}]}
    base.update(over)
    return base


class ValidationTests(unittest.TestCase):
    def test_invalid_snapshots_fail_closed(self):
        for bad in (None, [], {}, snapshot(host="evil.example"), snapshot(source="x"),
                    {k: v for k, v in snapshot().items() if k != "rooms"},
                    snapshot(rooms=[{"label": "x"}])):
            self.assertIsNone(inv.validate_inventory(bad))
            self.assertFalse(inv.summarize_inventory(bad)["valid"])

    def test_untrusted_strings_are_filtered_and_truncated(self):
        clean = inv.validate_inventory(snapshot(
            dates=["11/11", "<img onerror=x>", "99"],
            slots=[{"label": "not a slot", "kind": "time-box", "selected": False,
                    "book": False, "disabled": False},
                   {"label": "09:00-10:00", "kind": "evil kind!", "selected": False,
                    "book": False, "disabled": False}],
            rooms=[{"label": "X" * 500, "selected": False, "disabled": False}]))
        self.assertEqual(clean["dates"], ["11/11"])
        self.assertEqual(clean["slots"], [])
        self.assertEqual(len(clean["rooms"][0]["label"]), 40)


class ClassificationTests(unittest.TestCase):
    def test_known_rooms_map_to_config_and_unknown_are_flagged(self):
        summary = inv.summarize_inventory(snapshot())
        rooms_by_label = {r["label"]: r["configured_as"] for r in summary["rooms"]}
        self.assertEqual(rooms_by_label, {"P03 個人直播室": "p03", "P05 個人直播室": None})
        self.assertEqual(summary["unconfigured_rooms"], ["P05 個人直播室"])
        self.assertEqual(summary["unconfigured_status_labels"], ["新空間"])

    def test_slot_group_maps_to_flow_only_as_a_candidate(self):
        group = inv.summarize_inventory(snapshot())["slot_groups"][0]
        self.assertEqual((group["flow_candidate"], group["durations_hours"]), ("hourly_slot", [1.0]))
        self.assertEqual(group["confidence"], "SELECTOR_ONLY_NEEDS_LIVE_CHECK")

    def test_unknown_slot_class_is_a_new_unverified_flow(self):
        slots = [{"label": "09:00-12:00", "kind": "time-box3", "selected": False,
                  "book": True, "disabled": False}]
        group = inv.summarize_inventory(snapshot(slots=slots))["slot_groups"][0]
        self.assertIsNone(group["flow_candidate"])
        self.assertEqual(group["confidence"], "NEW_FLOW_UNVERIFIED")

    def test_ambiguous_room_tile_is_never_assigned(self):
        wide = copy.deepcopy(json.loads(rooms.DEFAULT_CONFIG.read_text(encoding="utf-8")))
        wide["rooms"]["music"]["tile_match"] = {"kind": "includes", "value": "室"}
        wide["rooms"]["music"]["sample_tile_label"] = "音樂創作室"
        # music "includes 室" would also match P03 -> config itself is rejected.
        with self.assertRaises(rooms.RoomConfigError):
            rooms.parse_config(wide)


class DraftTests(unittest.TestCase):
    def draft(self):
        summary = inv.summarize_inventory(snapshot())
        return inv.build_drafts(summary)

    def test_draft_is_created_for_unconfigured_room_only(self):
        drafts = self.draft()
        self.assertEqual(list(drafts), ["p05"])
        entry = drafts["p05"]
        self.assertEqual(entry["flow"], "hourly_slot")
        self.assertEqual(entry["tile_match"], {"kind": "regex", "value": "^P05(?:\\s|$)"})
        self.assertTrue(entry["submit_requires_ack"])
        self.assertEqual(entry["evidence"]["live"], "NOT_VERIFIED")

    def test_draft_cannot_be_activated_until_a_human_completes_it(self):
        data = json.loads(rooms.DEFAULT_CONFIG.read_text(encoding="utf-8"))
        data["rooms"]["p05"] = self.draft()["p05"]
        with self.assertRaises(rooms.RoomConfigError) as ctx:
            rooms.parse_config(data)
        self.assertIn("TODO", str(ctx.exception))

    def test_completed_draft_is_accepted_and_does_not_collide(self):
        data = completed_config()
        registry = rooms.parse_config(data)
        self.assertEqual(registry.keys, ("music", "p03", "p05"))
        self.assertEqual([p.key for p in registry.by_flow()["hourly_slot"]], ["p03", "p05"])

    def test_draft_keys_do_not_collide_with_existing_rooms(self):
        key, _ = inv.draft_room_entry("P03 個人直播室", ["09:00-10:00"], "hourly_slot", {"p03"})
        self.assertEqual(key, "p03_2")


def completed_config():
    """What a human would produce from the draft after checking the live site."""
    data = json.loads(rooms.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    entry = inv.build_drafts(inv.summarize_inventory(snapshot()))["p05"]
    entry.update(ui_label="P05 個人直播室（1 小時）", entry_label="個人直播室",
                 label="個人直播室 P05",
                 sample_tile_label="P05 個人直播室")
    entry["summary_match"] = {"text_all": ["個人直播室"], "regex_all": ["\\bP05\\b"]}
    entry["slots"] = {"kind": "hourly", "start": 9, "end": 20}
    entry["evidence"] = {"live": "NOT_VERIFIED", "live_notes": "僅離線驗證。", "source": "test"}
    data["rooms"]["p05"] = entry
    return data


@unittest.skipUnless(browser.available(), "NOT_VERIFIED: headless Chromium unavailable")
class InventoryScriptTests(unittest.TestCase):
    def test_script_reads_fixture_without_modifying_it(self):
        html = fx.grid_html(REGISTRY, "p03", DAY)
        case = {"id": "inv", "html": html, "steps": [
            fx.step("document.documentElement.outerHTML"), fx.step(inv.INVENTORY_JS),
            fx.step("document.documentElement.outerHTML")]}
        result = browser.run_cases([case])["inv"]
        self.assertIsNone(result["error"], result["error"])
        before, raw, after = result["steps"]
        self.assertEqual(before, after)
        summary = inv.summarize_inventory(raw)
        self.assertTrue(summary["valid"])
        configured = {r["configured_as"] for r in summary["rooms"]}
        self.assertEqual(configured, {"music", "p03", None})
        self.assertIn("P13 個人直播室", summary["unconfigured_rooms"])
        self.assertEqual(summary["slot_groups"][0]["flow_candidate"], "hourly_slot")

    def test_script_contains_no_side_effects(self):
        for forbidden in (".click(", "fetch(", "XMLHttpRequest", "document.cookie",
                          "localStorage", "location.reload", ".submit("):
            self.assertNotIn(forbidden, inv.INVENTORY_JS)

    def test_status_page_labels_are_inventoried(self):
        case = {"id": "st", "html": fx.status_html(REGISTRY), "url": fx.NCL_URL_STATUS,
                "steps": [fx.step(inv.INVENTORY_JS)]}
        raw = browser.run_cases([case])["st"]["steps"][0]
        summary = inv.summarize_inventory(raw)
        mapped = {i["label"]: i["configured_as"] for i in summary["status_labels"]}
        self.assertEqual(mapped["音樂創作室"], "music")
        self.assertEqual(mapped["個人直播室"], "p03")
        self.assertIsNone(mapped["討論室"])


@unittest.skipUnless(browser.available(), "NOT_VERIFIED: headless Chromium unavailable")
class ConfigOnlyNewRoomTests(unittest.TestCase):
    """Acceptance: a new room needs ONLY a config edit - no Python change at all."""

    def test_added_room_passes_the_whole_matrix_with_zero_code_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rooms.json"
            path.write_text(json.dumps(completed_config(), ensure_ascii=False), encoding="utf-8")
            env = {**os.environ, rooms.CONFIG_ENV: str(path)}
            probe = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, 'src'); import ncl_openlab_rooms as r; "
                 "print(','.join(r.get_registry().keys))"],
                cwd=HERE.parent, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(probe.stdout.strip(), "music,p03,p05", probe.stderr)
            done = subprocess.run(
                [sys.executable, "-m", "unittest", "tests.test_ncl_openlab_room_matrix",
                 "tests.test_ncl_openlab_legacy_parity", "-v"],
                cwd=HERE.parent, env=env, capture_output=True, text=True, timeout=600)
        output = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, output[-2000:])
        summary = output.strip().splitlines()[-1]
        self.assertEqual(summary, "OK", output[-500:])  # no skips, no failures


if __name__ == "__main__":
    unittest.main()
