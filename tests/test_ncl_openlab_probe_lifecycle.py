"""The read-only probe must leave Chrome open for manual inspection.

All fixtures are offline and never open a browser or submit reservations.
"""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ncl_openlab_probe as probe


class ProbeBrowserLifecycleTests(unittest.TestCase):
    def _run_inspect(self, *, current_url):
        browser = types.SimpleNamespace(
            get=AsyncMock(), stop=AsyncMock(),
        )
        tab = types.SimpleNamespace(evaluate=AsyncMock(side_effect=[
            current_url,
            {"host": probe.NCL_HOST, "results": {}},
            {"synthetic": True},
        ]))
        browser.get.return_value = tab

        zendriver = types.ModuleType("zendriver")
        zendriver.start = AsyncMock(return_value=browser)

        evidence = types.ModuleType("ncl_openlab_evidence")
        evidence.evidence_script = lambda: "EVIDENCE_SCRIPT"
        evidence.validate_evidence = lambda value: {"sanitized": True}
        slots = types.ModuleType("ncl_openlab_slots")
        slots.plan_time_slots = lambda *args: {"read_only": True}

        with (
            patch.dict(sys.modules, {
                "zendriver": zendriver,
                "ncl_openlab_evidence": evidence,
                "ncl_openlab_slots": slots,
            }),
            patch.object(probe.asyncio, "to_thread",
                         new_callable=AsyncMock),
            patch.object(probe, "wait_until_browser_manually_closed",
                         new_callable=AsyncMock) as wait_closed,
        ):
            if current_url.startswith("https://" + probe.NCL_HOST + "/"):
                asyncio.run(probe.inspect(
                    probe.next_open_date(), probe.SLOTS[:1]))
            else:
                with self.assertRaisesRegex(RuntimeError,
                                            "Not on the official"):
                    asyncio.run(probe.inspect(
                        probe.next_open_date(), probe.SLOTS[:1]))
            wait_closed.assert_awaited_once_with(browser)
            browser.stop.assert_not_awaited()

    def test_probe_success_preserves_page_until_manual_close(self):
        self._run_inspect(current_url="https://spms.ncl.edu.tw/NLT/co/")

    def test_probe_error_preserves_page_for_debugging(self):
        self._run_inspect(current_url="https://example.net/")


if __name__ == "__main__":
    unittest.main()
