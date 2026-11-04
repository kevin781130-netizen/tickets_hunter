"""Room configuration: validation, flow classification, compatibility constants."""
import copy
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ncl_openlab_autobook as app
import ncl_openlab_rooms as rooms
from ncl_openlab_guard import ROOM, VALID_SLOTS

RAW = json.loads(rooms.DEFAULT_CONFIG.read_text(encoding="utf-8"))


def mutated(fn):
    data = copy.deepcopy(RAW)
    fn(data)
    return data


class DefaultConfigTests(unittest.TestCase):
    def test_default_config_loads_and_lists_known_rooms(self):
        registry = rooms.load_config()
        self.assertEqual(registry.keys, ("music", "p03"))

    def test_legacy_constants_are_preserved(self):
        registry = rooms.get_registry()
        self.assertEqual(registry.room("music").slots, VALID_SLOTS)
        self.assertEqual(registry.room("music").entry_label, ROOM)
        self.assertEqual(app.ROOM_MODES, ("music", "p03"))
        self.assertEqual(app.P03_SLOTS,
                         tuple(f"{h:02d}:00-{h + 1:02d}:00" for h in range(9, 20)))

    def test_flows_group_rooms(self):
        grouped = rooms.get_registry().by_flow()
        self.assertEqual([p.key for p in grouped["block_slot"]], ["music"])
        self.assertEqual([p.key for p in grouped["hourly_slot"]], ["p03"])

    def test_each_tile_matcher_selects_only_its_own_room(self):
        registry = rooms.get_registry()
        for key, profile in registry.rooms.items():
            for other_key, other in registry.rooms.items():
                self.assertEqual(profile.tile_matches(other.sample_tile_label),
                                 key == other_key, (key, other_key))

    def test_live_evidence_is_not_overstated(self):
        registry = rooms.get_registry()
        self.assertEqual(registry.room("p03").live, "LIVE_VERIFIED")
        self.assertEqual(registry.room("music").live, "NOT_VERIFIED")

    def test_override_via_environment_path(self):
        data = mutated(lambda d: d["rooms"]["music"].update(label="音樂創作室測試"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rooms.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(rooms.load_config(path).room("music").label, "音樂創作室測試")


class ValidationTests(unittest.TestCase):
    def assertRejected(self, fn, fragment=None):
        with self.assertRaises(rooms.RoomConfigError) as ctx:
            rooms.parse_config(mutated(fn))
        if fragment:
            self.assertIn(fragment, str(ctx.exception))

    def test_unknown_schema_version_rejected(self):
        self.assertRejected(lambda d: d.update(schema_version=2), "schema_version")

    def test_room_must_reference_defined_flow(self):
        self.assertRejected(lambda d: d["rooms"]["p03"].update(flow="ghost"), "flow")

    def test_duplicate_flow_behaviour_rejected(self):
        def clone(d):
            d["flows"]["clone"] = dict(d["flows"]["hourly_slot"])
        self.assertRejected(clone, "identical behaviour")

    def test_slot_label_and_duplicates_rejected(self):
        self.assertRejected(lambda d: d["rooms"]["music"]["slots"]["values"].append("9:00-10"),
                            "invalid slot")
        self.assertRejected(lambda d: d["rooms"]["music"]["slots"]["values"].append("09:00-12:00"),
                            "duplicate")

    def test_hourly_range_bounds(self):
        self.assertRejected(lambda d: d["rooms"]["p03"]["slots"].update(end=30))

    def test_regex_constructs_and_syntax_rejected(self):
        self.assertRejected(lambda d: d["rooms"]["p03"]["tile_match"].update(value="(a+)+$"),
                            "unsupported")
        self.assertRejected(lambda d: d["rooms"]["p03"]["tile_match"].update(value="[unclosed"),
                            "not a valid pattern")

    def test_ambiguous_neighbour_rooms_rejected(self):
        def widen(d):
            d["rooms"]["p03"]["tile_match"] = {"kind": "includes", "value": "個人直播室"}
            d["rooms"]["p04"] = copy.deepcopy(d["rooms"]["p03"])
            d["rooms"]["p04"]["sample_tile_label"] = "P04 個人直播室"
            d["rooms"]["p04"]["summary_match"]["regex_all"] = []
        self.assertRejected(widen, "also matches")

    def test_tile_matcher_must_match_own_sample(self):
        self.assertRejected(lambda d: d["rooms"]["music"].update(sample_tile_label="別的房間"),
                            "sample_tile_label")

    def test_summary_must_match_own_sample(self):
        self.assertRejected(
            lambda d: d["rooms"]["p03"]["summary_match"].update(text_all=["不存在的文字"]),
            "summary_match")

    def test_todo_placeholders_cannot_be_activated(self):
        self.assertRejected(lambda d: d["rooms"]["p03"].update(entry_label="TODO"), "TODO")

    def test_evidence_state_must_be_known(self):
        self.assertRejected(lambda d: d["rooms"]["p03"]["evidence"].update(live="PASS"),
                            "evidence.live")

    def test_flags_must_be_booleans(self):
        self.assertRejected(lambda d: d["rooms"]["p03"].update(submit_requires_ack="yes"),
                            "true or false")

    def test_slot_selector_shape_is_restricted(self):
        self.assertRejected(
            lambda d: d["flows"]["hourly_slot"].update(slot_selector="div > *"),
            "slot_selector")

    def test_bad_json_reports_error_not_traceback_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(rooms.RoomConfigError):
                rooms.load_config(path)


class ClassificationTests(unittest.TestCase):
    def test_known_feature_sets_map_to_their_flow(self):
        for flow in rooms.get_registry().flows.values():
            features = {"slot_selector": flow.slot_selector,
                        "slot_requires_book_class": flow.slot_requires_book_class,
                        "book_class_marks_selected": flow.book_class_marks_selected}
            self.assertEqual(rooms.classify_flow(features), flow.name)

    def test_unknown_behaviour_is_not_forced_into_a_flow(self):
        self.assertIsNone(rooms.classify_flow(
            {"slot_selector": ".time-box3[data-param1]",
             "slot_requires_book_class": False, "book_class_marks_selected": False}))
        self.assertIsNone(rooms.classify_flow({}))
        self.assertIsNone(rooms.classify_flow(None))

    def test_support_matrix_never_claims_live_for_unverified_rooms(self):
        rows = {row["room"]: row for row in rooms.support_matrix()}
        self.assertEqual(rows["p03"]["status"], "SUPPORTED_LIVE_VERIFIED")
        self.assertEqual(rows["music"]["status"],
                         "SUPPORTED_OFFLINE_ONLY_LIVE_NOT_VERIFIED")


class PickerModelTests(unittest.TestCase):
    def test_gui_choices_and_slots_follow_the_config(self):
        import ncl_openlab_picker_model as model
        registry = rooms.get_registry()
        self.assertEqual(model.ROOM_CHOICES,
                         {k: p.ui_label for k, p in registry.rooms.items()})
        for key, profile in registry.rooms.items():
            self.assertEqual(model.available_slots(key), profile.slots)
        with self.assertRaises(ValueError):
            model.available_slots("nope")

    def test_gui_never_acknowledges_an_unverified_room_for_the_user(self):
        import dataclasses
        from datetime import date
        import ncl_openlab_picker_model as model
        registry = rooms.get_registry()
        flagged = dataclasses.replace(registry.room("music"), submit_requires_ack=True)
        fake = rooms.RoomRegistry(flows=registry.flows, rooms={**registry.rooms, "music": flagged})
        kwargs = dict(day=date(2026, 11, 12), room="music", slots=("13:00-16:00",),
                      auto_submit=True)
        with unittest.mock.patch.object(model, "get_registry", lambda: fake):
            with self.assertRaises(ValueError) as ctx:
                model.build_booking_args(**kwargs)
        self.assertIn("--ack-room-unverified", str(ctx.exception))
        self.assertIn("--auto-submit", model.build_booking_args(**kwargs))


if __name__ == "__main__":
    unittest.main()
