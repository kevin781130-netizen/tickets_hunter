"""Diagnostics, dry-run, reports, screenshots and CLI safety gates (all offline)."""
import asyncio
import contextlib
import dataclasses
import json
import sys
import tempfile
import types
import unittest
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import ncl_browser as browser
import ncl_fixtures as fx
import ncl_openlab_autobook as app
import ncl_openlab_diag as diag
from ncl_openlab_rooms import RoomRegistry, get_registry

DAY = date(2026, 11, 11)
REGISTRY = get_registry()


class OutcomeExplanationTests(unittest.TestCase):
    def test_known_and_prefixed_codes_are_categorised(self):
        self.assertEqual(diag.explain_outcome("SUCCESS_PAGE_MATCHED")["category"], "SUCCESS_CONFIRMED")
        self.assertEqual(diag.explain_outcome("SUBMITTED_SUCCESS_UNVERIFIED")["category"],
                         "UNKNOWN_DO_NOT_RETRY")
        self.assertEqual(diag.explain_outcome("BLOCKED_SLOT_NOT_BOOK_CLASS")["category"], "BLOCKED")
        self.assertEqual(diag.explain_outcome("RELEASE_WINDOW_EXHAUSTED_NO_BOOKABLE_UI_SLOT")["category"],
                         "WINDOW_EXHAUSTED")
        self.assertEqual(diag.explain_outcome("EXCEPTION_RuntimeError")["category"], "ERROR")
        self.assertEqual(diag.explain_outcome("SOMETHING_NEW")["category"], "UNCLASSIFIED")

    def test_uncertain_outcomes_never_suggest_retry(self):
        for code in ("SUBMITTED_SUCCESS_UNVERIFIED", "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY",
                     "FIRST_UNVERIFIED_SECOND_NOT_ATTEMPTED_X"):
            self.assertEqual(diag.explain_outcome(code)["category"], "UNKNOWN_DO_NOT_RETRY")

    def test_every_retryable_code_in_the_engine_is_explained(self):
        for code in app.RETRYABLE_BEFORE_SUBMIT:
            self.assertEqual(diag.explain_outcome(code)["category"], "RETRYABLE_BEFORE_SUBMIT", code)


class ReportTests(unittest.TestCase):
    def test_trace_sanitizer_drops_anything_that_is_not_a_short_code(self):
        clean = diag.sanitize_trace([("date", "CLICKED"), ("x", "<script>alert(1)</script>"),
                                     "not-a-pair", ("slot 13:00-14:00", "SLOT_DISABLED")])
        self.assertEqual([c["code"] for c in clean],
                         ["CLICKED", "REDACTED", "REDACTED", "SLOT_DISABLED"])

    def test_report_has_no_secret_like_fields_and_never_overwrites(self):
        report = diag.build_report(day=DAY, mode="p03", priorities=("13:00-14:00",),
                                   outcome="SUCCESS_PAGE_MATCHED", trace=[("date", "CLICKED")],
                                   flags={"auto_submit": True, "dry_run": False})
        text = json.dumps(report, ensure_ascii=False).lower()
        for forbidden in ("cookie", "password", "token", "authorization", "email"):
            self.assertNotIn(forbidden, text.replace("no page text, cookies, credentials", ""))
        with tempfile.TemporaryDirectory() as tmp:
            first = diag.write_report(tmp, report, stem="run")
            second = diag.write_report(tmp, report, stem="run")
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["target"]["room"], "p03")

    def test_unknown_room_cannot_produce_a_report(self):
        with self.assertRaises(ValueError):
            diag.build_report(day=DAY, mode="nope", priorities=(), outcome="X", trace=[], flags={})


class DiagnoseLogicTests(unittest.TestCase):
    def raw(self, **over):
        group = lambda **kw: {"count": 1, "disabled": 0, "selected": 0, "book": 0, **kw}  # noqa: E731
        base = {"host": "spms.ncl.edu.tw", "stage": "DATE_GRID", "date": group(),
                "room": group(), "slot": group(book=1), "slots_visible": 3,
                "slot_classes": ["book", "time-box2"], "gobook_count": 0}
        base.update(over)
        return base

    def test_clean_page_is_ready_but_availability_is_never_claimed(self):
        result = diag.diagnose(self.raw(), "music")
        self.assertTrue(result["ready_to_select"])
        self.assertFalse(result["availability_verified"])
        self.assertEqual(result["findings"], ["TARGET_VISIBLE_UI_ONLY"])

    def test_findings_for_each_failure_shape(self):
        zero = {"count": 0, "disabled": 0, "selected": 0, "book": 0}
        two = {"count": 2, "disabled": 0, "selected": 0, "book": 0}
        off = {"count": 1, "disabled": 1, "selected": 0, "book": 0}
        self.assertIn("DATE_NOT_FOUND", diag.diagnose(self.raw(date=zero), "music")["findings"])
        self.assertIn("ROOM_NOT_UNIQUE", diag.diagnose(self.raw(room=two), "music")["findings"])
        self.assertIn("DATE_DISABLED", diag.diagnose(self.raw(date=off), "music")["findings"])
        self.assertIn("SLOT_NOT_RENDERED_OR_NOT_IN_VIEW",
                      diag.diagnose(self.raw(slot=zero), "music")["findings"])
        self.assertIn("SLOT_DISABLED_UI_HINT", diag.diagnose(self.raw(slot=off), "music")["findings"])

    def test_missing_book_class_only_matters_for_flows_that_require_it(self):
        nobook = {"count": 1, "disabled": 0, "selected": 0, "book": 0}
        self.assertIn("SLOT_MISSING_REQUIRED_BOOK_CLASS",
                      diag.diagnose(self.raw(slot=nobook), "music")["findings"])
        self.assertEqual(diag.diagnose(self.raw(slot=nobook), "p03")["findings"],
                         ["TARGET_VISIBLE_UI_ONLY"])

    def test_wrong_stage_and_malformed_results_fail_closed(self):
        self.assertIn("NOT_ON_DATE_GRID_CHECKOUT",
                      diag.diagnose(self.raw(stage="CHECKOUT"), "music")["findings"])
        for bad in (None, {}, self.raw(host="evil.example"), self.raw(stage="WHAT"),
                    self.raw(slot_classes=["secret-token"]), self.raw(slots_visible=-1),
                    self.raw(date={"count": "1"})):
            result = diag.diagnose(bad, "music")
            self.assertEqual(result["findings"], ["DIAG_RESULT_INVALID"])
            self.assertFalse(result["ready_to_select"])

    def test_script_is_read_only_and_validates_inputs(self):
        js = diag.diagnose_script(DAY, "13:00-16:00", "music")
        for forbidden in (".click(", "fetch(", "XMLHttpRequest", "document.cookie",
                          "localStorage", "location.reload", "submit("):
            self.assertNotIn(forbidden, js)
        with self.assertRaises(ValueError):
            diag.diagnose_script(DAY, "13:00-14:00", "music")
        with self.assertRaises(ValueError):
            diag.diagnose_script(DAY, "13:00-16:00", "nope")


@unittest.skipUnless(browser.available(), "NOT_VERIFIED: headless Chromium unavailable")
class DiagnoseInBrowserTests(unittest.TestCase):
    def test_diag_script_sees_the_fixture_and_changes_nothing(self):
        cases, rooms = [], list(REGISTRY.rooms.values())
        for profile in rooms:
            slot = profile.slots[0]
            for label, kw in (("ok", {}), ("disabled", {"slot_state": "disabled"}),
                              ("dup", {"dup_room": True}), ("nodate", {"date_missing": True})):
                html = fx.grid_html(REGISTRY, profile.key, DAY, **kw)
                cases.append({"id": f"{profile.key}|{label}", "html": html, "steps": [
                    fx.step("document.documentElement.outerHTML"),
                    fx.step(diag.diagnose_script(DAY, slot, profile.key)),
                    fx.step("document.documentElement.outerHTML")]})
        results = browser.run_cases(cases)
        for profile in rooms:
            def run(label):
                r = results[f"{profile.key}|{label}"]
                self.assertIsNone(r["error"], r["error"])
                before, raw, after = r["steps"]
                self.assertEqual(before, after, "diagnostics must not mutate the page")
                return diag.diagnose(raw, profile.key)
            self.assertTrue(run("ok")["ready_to_select"], profile.key)
            self.assertIn("SLOT_DISABLED_UI_HINT", run("disabled")["findings"])
            self.assertIn("ROOM_NOT_UNIQUE", run("dup")["findings"])
            self.assertIn("DATE_NOT_FOUND", run("nodate")["findings"])


class FakeTab:
    """Records every script; refuses anything that is not a read-only diagnostic."""
    def __init__(self, diag_result):
        self.scripts, self.diag_result, self.shots = [], diag_result, []

    async def evaluate(self, script):
        self.scripts.append(script)
        if script == "location.href":
            return "https://spms.ncl.edu.tw/NLT/co/media_discussion.jsp"
        return self.diag_result

    async def save_screenshot(self, path):
        self.shots.append(path)
        Path(path).write_bytes(b"\x89PNG fake")

    async def get(self, url):
        raise AssertionError("dry-run must not navigate")


class FakeBrowser:
    stopped = True

    def __init__(self, tab):
        self.tab = tab

    async def get(self, url):
        return self.tab


def run_autobook(tab, **kwargs):
    browser_obj = FakeBrowser(tab)

    async def start(**_):
        return browser_obj

    async def ready(*a, **k):
        return "GRID_READY"

    async def prompt(*a, **k):
        return ""

    with (patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(start=start)}),
          patch.object(app, "ensure_date_grid", ready),
          patch.object(app.asyncio, "to_thread", prompt),
          contextlib.redirect_stdout(StringIO())):
        return asyncio.run(app.autobook(DAY, kwargs.pop("priorities"), **kwargs))


GOOD_DIAG = {"host": "spms.ncl.edu.tw", "stage": "DATE_GRID",
             "date": {"count": 1, "disabled": 0, "selected": 0, "book": 0},
             "room": {"count": 1, "disabled": 0, "selected": 0, "book": 0},
             "slot": {"count": 1, "disabled": 0, "selected": 0, "book": 0},
             "slots_visible": 11, "slot_classes": ["time-box"], "gobook_count": 0}


class DryRunTests(unittest.TestCase):
    def test_dry_run_only_evaluates_diagnostics_and_writes_report_and_screenshot(self):
        tab = FakeTab(GOOD_DIAG)
        with tempfile.TemporaryDirectory() as tmp:
            outcome = run_autobook(tab, priorities=("13:00-14:00", "14:00-15:00"),
                                   auto_submit=False, mode="p03", dry_run=True,
                                   report_dir=tmp, screenshot=True)
            self.assertEqual(outcome, "DRY_RUN_COMPLETE")
            reports = sorted(Path(tmp).glob("ncl_run_*.json"))
            self.assertEqual(len(reports), 1)
            data = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(data["outcome"]["category"], "DRY_RUN")
            self.assertTrue(data["flags"]["dry_run"])
            self.assertEqual(set(data["diagnosis"]), {"13:00-14:00", "14:00-15:00"})
            self.assertEqual(len(tab.shots), 1)
            self.assertTrue(data["screenshot"].endswith(".png"))
        action_phases = [s for s in tab.scripts if s != "location.href"]
        self.assertEqual(len(action_phases), 2)
        for script in action_phases:
            self.assertIn("const allow =", script)  # diagnostics script only
            self.assertNotIn(".click(", script)

    def test_dry_run_with_auto_submit_is_refused_before_any_browser_work(self):
        tab = FakeTab(GOOD_DIAG)
        outcome = run_autobook(tab, priorities=("13:00-14:00",), auto_submit=True,
                               mode="p03", dry_run=True)
        self.assertEqual(outcome, "INVALID_DRY_RUN_WITH_AUTO_SUBMIT")
        self.assertEqual(tab.scripts, [])

    def test_no_report_or_screenshot_unless_requested(self):
        tab = FakeTab(GOOD_DIAG)
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
            run_autobook(tab, priorities=("13:00-14:00",), auto_submit=False, mode="p03",
                         dry_run=True)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertEqual(tab.shots, [])

    def test_booking_run_report_contains_trace_and_outcome(self):
        tab = FakeTab(GOOD_DIAG)

        async def fake_book(tab_, day, priorities, **kwargs):
            app._note("date", "CLICKED")
            app._note("slot 13:00-14:00", "SLOT_DISABLED")
            return "NO_BOOKABLE_UI_SLOT"

        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "book_one_target", fake_book):
            outcome = run_autobook(tab, priorities=("13:00-14:00",), auto_submit=True,
                                   now_mode=True, mode="p03", report_dir=tmp)
            self.assertEqual(outcome, "NO_BOOKABLE_UI_SLOT")
            data = json.loads(next(Path(tmp).glob("ncl_run_*.json")).read_text(encoding="utf-8"))
            self.assertEqual(data["outcome"]["category"], "RETRYABLE_BEFORE_SUBMIT")
            self.assertEqual([t["code"] for t in data["trace"]], ["CLICKED", "SLOT_DISABLED"])
            self.assertEqual(data["target"]["flow"], "hourly_slot")

    def test_exception_is_reported_and_still_propagates(self):
        tab = FakeTab(GOOD_DIAG)

        async def boom(*a, **k):
            return "ENTRY_NOT_FOUND_OR_AMBIGUOUS"

        browser_obj = FakeBrowser(tab)

        async def start(**_):
            return browser_obj

        async def prompt(*a, **k):
            return ""

        with tempfile.TemporaryDirectory() as tmp:
            with (patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(start=start)}),
                  patch.object(app, "ensure_date_grid", boom),
                  patch.object(app.asyncio, "to_thread", prompt),
                  contextlib.redirect_stdout(StringIO())):
                with self.assertRaises(RuntimeError):
                    asyncio.run(app.autobook(DAY, ("13:00-14:00",), auto_submit=False,
                                             mode="p03", report_dir=tmp))
            data = json.loads(next(Path(tmp).glob("ncl_run_*.json")).read_text(encoding="utf-8"))
            self.assertEqual(data["outcome"]["code"], "EXCEPTION_RuntimeError")

    def test_report_failure_never_changes_the_booking_outcome(self):
        tab = FakeTab(GOOD_DIAG)

        async def fake_book(*a, **k):
            return "SUCCESS_PAGE_MATCHED"

        with (patch.object(app, "book_one_target", fake_book),
              patch("ncl_openlab_diag.write_report", side_effect=OSError("disk full"))):
            outcome = run_autobook(tab, priorities=("13:00-14:00",), auto_submit=True,
                                   now_mode=True, mode="p03", report_dir="unused")
        self.assertEqual(outcome, "SUCCESS_PAGE_MATCHED")


def cli(argv, registry=None):
    patches = [patch.object(sys, "argv", ["app"] + argv),
               patch.object(app.asyncio, "run", return_value="MOCK")]
    if registry is not None:
        patches.append(patch.object(app, "_REGISTRY", registry))
    out, err = StringIO(), StringIO()
    with contextlib.ExitStack() as stack:
        runner = None
        for p in patches:
            handle = stack.enter_context(p)
            if p is patches[1]:
                runner = handle
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        try:
            app.main()
            code, kwargs = 0, None
            if runner.call_args:
                coro = runner.call_args.args[0]
                kwargs = dict(coro.cr_frame.f_locals)
                coro.close()
        except SystemExit as exc:
            code, kwargs = exc.code, None
    return code, kwargs, out.getvalue(), err.getvalue()


class CliSafetyTests(unittest.TestCase):
    BASE = ["--date", "2026-11-12", "--room", "p03", "--slot", "13:00-14:00"]

    def test_dry_run_passes_flags_and_defaults_report_dir(self):
        code, kw, _, _ = cli(self.BASE + ["--dry-run"])
        self.assertEqual(code, 0)
        self.assertTrue(kw["dry_run"])
        self.assertFalse(kw["auto_submit"])
        self.assertEqual(kw["report_dir"], "ncl_reports")

    def test_dry_run_conflicts_are_rejected(self):
        for extra in (["--dry-run", "--auto-submit"], ["--dry-run", "--reserve-two"]):
            self.assertEqual(cli(self.BASE + extra)[0], 2, extra)

    def test_screenshot_needs_a_report_destination(self):
        self.assertEqual(cli(self.BASE + ["--screenshot"])[0], 2)
        code, kw, _, _ = cli(self.BASE + ["--screenshot", "--report-dir", "r"])
        self.assertEqual((code, kw["screenshot"], kw["report_dir"]), (0, True, "r"))

    def test_plan_only_never_starts_a_browser(self):
        with patch.object(sys, "argv", ["app"] + self.BASE + ["--plan-only", "--auto-submit"]), \
                patch.object(app.asyncio, "run") as runner, \
                contextlib.redirect_stdout(StringIO()) as out:
            app.main()
        runner.assert_not_called()
        plan = json.loads(out.getvalue().strip().splitlines()[-1])["plan"]
        self.assertEqual((plan["room"], plan["flow"], plan["live_evidence"]),
                         ("p03", "hourly_slot", "LIVE_VERIFIED"))
        self.assertEqual(plan["release_taipei"], "2026-11-05T00:00:00+08:00")

    def test_unverified_music_never_submits_even_with_acknowledgement(self):
        args = ["--date", "2026-11-12", "--auto-submit"]
        for extra in ([], ["--ack-room-unverified"]):
            code, kw, _, err = cli(args + extra)
            self.assertEqual(code, 2)
            self.assertIsNone(kw)
            self.assertIn("NOT_VERIFIED", err)
        code, kw, out, _ = cli(["--date", "2026-11-12"])
        self.assertEqual(code, 0)  # preview is still permitted
        self.assertIn("NOT_VERIFIED", out)
        self.assertFalse(kw["auto_submit"])

    def test_verified_room_flagged_for_acknowledgement_needs_explicit_flag_to_submit(self):
        p03 = dataclasses.replace(REGISTRY.room("p03"), submit_requires_ack=True)
        registry = RoomRegistry(flows=REGISTRY.flows,
                                rooms={**REGISTRY.rooms, "p03": p03},
                                categories=REGISTRY.categories)
        args = ["--date", "2026-11-12", "--room", "p03",
                "--slot", "13:00-14:00", "--auto-submit"]
        self.assertEqual(cli(args, registry)[0], 2)
        self.assertEqual(cli(args + ["--ack-room-unverified"], registry)[0], 0)
        self.assertEqual(cli(args[:-1], registry)[0], 0)  # preview needs no ack


if __name__ == "__main__":
    unittest.main()
