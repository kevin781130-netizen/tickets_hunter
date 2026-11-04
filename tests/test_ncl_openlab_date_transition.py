"""Offline regression: NCL date/room redraw can lag behind a click.

Never opens Chrome or submits a reservation. Transient checks only re-read DOM.
"""
import asyncio
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ncl_openlab_autobook as ncl

DAY = date(2026, 11, 11)
SLOT = "16:00-17:00"


class DateTransitionTests(unittest.TestCase):
    def test_room_rechecks_after_date_clicked_without_recursing_date(self):
        calls, sleeps = [], []

        async def fake_action(tab, phase, day, slot, mode):
            calls.append(phase)
            return ("DATE_NOT_SELECTED" if len(calls) < 3
                    else "CLICKED")

        async def fake_sleep(duration):
            sleeps.append(duration)

        with (patch.object(ncl, "read_action", fake_action),
              patch.object(ncl.asyncio, "sleep", fake_sleep)):
            result = asyncio.run(ncl.attempt_stage(
                object(), "room", DAY, SLOT, attempts=8, mode="p03"))

        self.assertEqual(result, "CLICKED")
        self.assertEqual(calls, ["room"] * 3)
        self.assertEqual(sleeps, [0.2, 0.2])

    def test_persistently_unselected_date_fails_closed(self):
        calls = []

        async def fake_action(tab, phase, day, slot, mode):
            calls.append(phase)
            return "DATE_NOT_SELECTED"

        async def fake_sleep(duration):
            return None

        with (patch.object(ncl, "read_action", fake_action),
              patch.object(ncl.asyncio, "sleep", fake_sleep)):
            result = asyncio.run(ncl.attempt_stage(
                object(), "room", DAY, SLOT, attempts=5, mode="p03"))

        self.assertEqual(result, "DATE_NOT_SELECTED")
        self.assertEqual(calls, ["room"] * 5)

    def test_slot_waits_for_room_selection_without_extra_click(self):
        calls = []

        async def fake_action(tab, phase, day, slot, mode):
            calls.append(phase)
            return "CONTEXT_NOT_SELECTED" if len(calls) == 1 else "CLICKED"

        async def fake_sleep(duration):
            return None

        with (patch.object(ncl, "read_action", fake_action),
              patch.object(ncl.asyncio, "sleep", fake_sleep)):
            result = asyncio.run(ncl.attempt_stage(
                object(), "slot", DAY, SLOT, attempts=3, mode="p03"))
        self.assertEqual(result, "CLICKED")
        self.assertEqual(calls, ["slot", "slot"])

    def test_never_retries_a_final_submission_result(self):
        calls = []

        async def fake_action(tab, phase, day, slot, mode):
            calls.append(phase)
            return "ALREADY_SUBMITTED"

        async def fake_sleep(duration):
            raise AssertionError("Final submit must never wait or retry")

        with (patch.object(ncl, "read_action", fake_action),
              patch.object(ncl.asyncio, "sleep", fake_sleep)):
            result = asyncio.run(ncl.attempt_stage(
                object(), "submit", DAY, SLOT, attempts=8, mode="p03"))
        self.assertEqual(result, "ALREADY_SUBMITTED")
        self.assertEqual(calls, ["submit"])


if __name__ == "__main__":
    unittest.main()
