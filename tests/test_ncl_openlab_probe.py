"""Offline tests for the read-only NCL OPEN LAB adapter."""
import importlib.util
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "ncl_openlab_probe.py"
SPEC = importlib.util.spec_from_file_location("ncl_openlab_probe", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class NclProbeTests(unittest.TestCase):
    def test_seven_days_ahead_at_taipei_midnight(self):
        local = datetime(2026, 11, 4, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(mod.next_open_date(local), date(2026, 11, 11))

    def test_timezone_normalization(self):
        utc = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)
        self.assertEqual(mod.next_open_date(utc), date(2026, 11, 11))

    def test_single_slot_is_targeted(self):
        self.assertEqual(
            mod.probe_needles(date(2026, 11, 11), "09:00-12:00"),
            ["11/11", "音樂創作室", "09:00-12:00"],
        )

    def test_invalid_slot_is_rejected(self):
        with self.assertRaises(ValueError):
            mod.probe_needles(date(2026, 11, 11), "10:00-11:00")

    def test_script_has_no_actions(self):
        script = mod.probe_script(date(2026, 11, 11))
        self.assertIn(json.dumps(["11/11", "音樂創作室", *mod.SLOTS], ensure_ascii=False), script)
        for forbidden in (".click(", ".submit(", "fetch(", ".reload(", ".dispatchEvent("):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
