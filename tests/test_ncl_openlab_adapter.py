"""Offline safety and compatibility checks for the not-yet-routed NCL adapter."""
import asyncio
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from platforms import ncl_openlab as adapter


DAY = date(2026, 11, 12)


class AdapterTests(unittest.TestCase):
    def test_passive_router_entry_never_books_on_official_host(self):
        with patch.object(adapter.ncl, "book_one_target",
                          new_callable=AsyncMock) as booking:
            result = asyncio.run(adapter.nodriver_ncl_main(
                None, "https://spms.ncl.edu.tw/NLT/co/media_discussion.jsp",
                {"ncl_openlab": {"enabled": True, "auto_submit": True}}))
        self.assertEqual(result, "NCL_MANUAL_BOOKING_ONLY")
        booking.assert_not_awaited()

    def test_passive_router_rejects_external_hostname(self):
        result = asyncio.run(adapter.nodriver_ncl_main(
            None, "https://spms.ncl.edu.tw.evil.example/", {}))
        self.assertEqual(result, "NCL_HOST_NOT_MATCHED")

    def test_disabled_by_default_even_with_valid_slot(self):
        with patch.object(adapter.ncl, "book_one_target",
                          new_callable=AsyncMock) as booking:
            result = asyncio.run(adapter.nodriver_ncl_booking(
                None, DAY, "13:00-16:00"))
        self.assertEqual(result, "NCL_ADAPTER_SUBMIT_NOT_AUTHORIZED")
        booking.assert_not_awaited()

    def test_invalid_date_room_and_slot_block_before_browser(self):
        cases = [
            (datetime(2026, 11, 12), "music", "13:00-16:00",
             "NCL_ADAPTER_INVALID_DATE"),
            ("2026-11-12", "music", "13:00-16:00",
             "NCL_ADAPTER_INVALID_DATE"),
            (DAY, "unknown", "13:00-16:00",
             "NCL_ADAPTER_INVALID_ROOM"),
            (DAY, "p03", "13:00-16:00",
             "NCL_ADAPTER_INVALID_SLOT"),
            (DAY, "music", "13:00-14:00",
             "NCL_ADAPTER_INVALID_SLOT"),
        ]
        for day, mode, slot, expected in cases:
            with self.subTest(mode=mode, slot=slot):
                with patch.object(adapter.ncl, "at_official_host",
                                  new_callable=AsyncMock) as host:
                    result = asyncio.run(adapter.nodriver_ncl_booking(
                        None, day, slot, mode=mode, auto_submit=True))
                    self.assertEqual(result, expected)
                    host.assert_not_awaited()

    def test_wrong_site_blocks_entry(self):
        with (
            patch.object(adapter.ncl, "at_official_host",
                         new_callable=AsyncMock, return_value=False),
            patch.object(adapter.ncl, "ensure_date_grid",
                         new_callable=AsyncMock) as entry,
        ):
            result = asyncio.run(adapter.nodriver_ncl_booking(
                object(), DAY, "13:00-16:00", auto_submit=True))
            self.assertEqual(result, "NCL_ADAPTER_WRONG_HOST")
            entry.assert_not_awaited()

    def test_agreement_required_does_not_submit(self):
        with (
            patch.object(adapter.ncl, "at_official_host",
                         new_callable=AsyncMock, return_value=True),
            patch.object(adapter.ncl, "ensure_date_grid",
                         new_callable=AsyncMock,
                         return_value="AGREEMENT_REQUIRED"),
            patch.object(adapter.ncl, "book_one_target",
                         new_callable=AsyncMock) as book,
        ):
            outcome = asyncio.run(adapter.nodriver_ncl_booking(
                object(), DAY, "13:00-16:00", auto_submit=True))
            self.assertEqual(
                outcome, "NCL_ADAPTER_ENTRY_BLOCKED_AGREEMENT_REQUIRED")
            book.assert_not_awaited()

    def test_music_success_reuses_existing_single_submit(self):
        tab = object()
        with (
            patch.object(adapter.ncl, "at_official_host",
                         new_callable=AsyncMock, return_value=True),
            patch.object(adapter.ncl, "ensure_date_grid",
                         new_callable=AsyncMock, return_value="GRID_READY"),
            patch.object(adapter.ncl, "book_one_target",
                         new_callable=AsyncMock,
                         return_value="SUCCESS_PAGE_MATCHED") as book,
        ):
            outcome = asyncio.run(adapter.nodriver_ncl_booking(
                tab, DAY, "13:00-16:00", auto_submit=True))
            self.assertEqual(outcome, "SUCCESS_PAGE_MATCHED")
            book.assert_awaited_once_with(
                tab, DAY, ("13:00-16:00",),
                mode="music", auto_submit=True)

    def test_p03_uncertain_result_is_not_retried(self):
        tab = object()
        with (
            patch.object(adapter.ncl, "at_official_host",
                         new_callable=AsyncMock, return_value=True),
            patch.object(adapter.ncl, "ensure_date_grid",
                         new_callable=AsyncMock, return_value="GRID_READY"),
            patch.object(adapter.ncl, "book_one_target",
                         new_callable=AsyncMock,
                         return_value="SUBMITTED_SUCCESS_UNVERIFIED") as book,
        ):
            result = asyncio.run(adapter.nodriver_ncl_booking(
                tab, DAY, "13:00-14:00", mode="p03", auto_submit=True))
            self.assertEqual(result, "SUBMITTED_SUCCESS_UNVERIFIED")
            book.assert_awaited_once_with(
                tab, DAY, ("13:00-14:00",),
                mode="p03", auto_submit=True)


if __name__ == "__main__":
    unittest.main()
