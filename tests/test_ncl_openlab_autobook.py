"""Offline safety checks for a single-shot, opt-in NCL reservation workflow."""
import asyncio
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ncl_openlab_autobook import (
    PHASES, action_script, release_time, seconds_until_release,
    attempt_stage
)


DAY = date(2026, 11, 12)
SLOT = "09:00-12:00"


class AutoBookTests(unittest.TestCase):
    def test_all_steps_include_real_ui_selection_and_submit(self):
        self.assertEqual(PHASES, ("date", "room", "slot", "next",
                                  "submit", "success"))

    def test_music_room_uses_true_timebox2(self):
        js = action_script("slot", DAY, SLOT)
        self.assertIn(".time-box2[data-param1]", js)
        self.assertIn('"09:00-12:00"', js)
        self.assertIn('"音樂創作室"', js)

    def test_explicit_book_ui_hint(self):
        js = action_script("slot", DAY, SLOT)
        self.assertIn('classList.contains("book")', js)
        self.assertIn('SLOT_NOT_BOOK_CLASS', js)

    def test_disabling_and_reserving_are_hard_blocks(self):
        js = action_script("slot", DAY, SLOT)
        self.assertIn('classList.contains("disabled")', js)
        self.assertIn('classList.contains("reserving")', js)
        self.assertIn('"SLOT_DISABLED"', js)

    def test_date_and_room_must_be_selected(self):
        js = action_script("slot", DAY, SLOT)
        self.assertIn(".date-box", js)
        self.assertIn(".space-box1", js)
        self.assertIn('classList.contains("selected")', js)
        self.assertIn('"CONTEXT_NOT_SELECTED"', js)

    def test_exact_final_summary_and_single_submission(self):
        js = action_script("submit", DAY, SLOT)
        self.assertIn('"2026/11/12"', js)
        self.assertIn('"音樂創作室"', js)
        self.assertIn('summary()', js)
        self.assertIn('window.__nclOneShotSubmit', js)
        self.assertIn('button#gobook.submit-circle-button', js)
        self.assertIn('button.getAttribute("data-param2") !== task.isoDate', js)
        self.assertIn('button.getAttribute("data-param5") !== task.slot', js)
        self.assertIn('READY_FOR_POINTER_CLICK', js)
        self.assertNotIn('button.click(); return result("CLICKED_ONCE")', js)

    def test_no_private_details_reported(self):
        js = action_script("success", DAY, SLOT)
        self.assertIn("SUCCESS_PAGE_MATCHED", js)
        self.assertIn("SUCCESS_NOT_VERIFIED", js)
        self.assertNotIn("document.cookie", js)
        self.assertNotIn("localStorage", js)
        self.assertNotIn("sessionStorage", js)
        self.assertNotIn("email", js.lower())

    def test_no_backend_api_or_captcha_bypass(self):
        js = action_script("submit", DAY, SLOT)
        for forbidden in ("fetch(", "XMLHttpRequest", "webdriver",
                          "captcha", "CAPTCHA", "turnstile", "axios",
                          "location.reload(", "setInterval("):
            self.assertNotIn(forbidden, js)

    def test_invalid_phase_rejected(self):
        with self.assertRaises(ValueError):
            action_script("checkout_anything", DAY, SLOT)

    def test_invalid_one_hour_slot_rejected(self):
        with self.assertRaises(ValueError):
            action_script("slot", DAY, "09:00-10:00")

    def test_invalid_datetime_target_rejected(self):
        with self.assertRaises(ValueError):
            action_script("date", datetime(2026, 11, 12), SLOT)

    def test_release_day_is_seven_days_before(self):
        self.assertEqual(release_time(DAY).isoformat(),
                         "2026-11-05T00:00:00+08:00")

    def test_release_difference_is_taipei_timezone(self):
        current = datetime(2026, 11, 4, 23, 58, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(seconds_until_release(DAY, current), 120.0)

    def test_local_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            seconds_until_release(DAY, datetime(2026, 11, 4, 23, 58))

    def test_unsupported_older_date_rejected(self):
        with self.assertRaises(ValueError):
            release_time(datetime(2026, 11, 12))

    def test_single_keyboard_submit_does_not_repeat_when_uncertain(self):
        import ncl_openlab_autobook as module
        import types
        from unittest.mock import patch

        class FakeElement:
            def __init__(self, tab):
                self.tab = tab

            async def send_keys(self, key):
                self.tab.events.append(("send_keys", key))
                if self.tab.failure:
                    raise RuntimeError("uncertain response after key dispatch")

            async def click(self):
                raise AssertionError("JS element.click must not be used")

        class FakeTab:
            def __init__(self, failure=False, missing=False):
                self.failure = failure
                self.missing = missing
                self.events = []

            async def evaluate(self, code):
                if code == "location.href":
                    return "https://spms.ncl.edu.tw/confirmation"
                if code == module.SUBMIT_PROBE_ARM_JS:
                    return "ARMED"
                if code == module.SUBMIT_PROBE_READ_JS:
                    return {"click": True, "trusted": True, "ajax": True}
                self.events.append("preflight")
                return {"code": "READY_FOR_POINTER_CLICK", "x": 200.0, "y": 350.0}

            async def select(self, selector, timeout=10):
                self.events.append(("select", selector, timeout))
                return None if self.missing else FakeElement(self)

            async def mouse_click(self, x, y):
                raise AssertionError("raw coordinate click must not be used")

        async def one(tab):
            return await module.submit_once_with_pointer(
                tab, DAY, SLOT, mode="music", attempts=8)

        stub = types.ModuleType("zendriver.core.keys")
        stub.SpecialKeys = types.SimpleNamespace(SPACE="SPACE_KEY")
        with patch.dict(sys.modules, {"zendriver.core.keys": stub}):
            tab = FakeTab()
            self.assertEqual(asyncio.run(one(tab)), "CLICKED_ONCE")
            self.assertEqual(tab.events.count(("send_keys", "SPACE_KEY")), 1)
            self.assertEqual([e for e in tab.events if
                              isinstance(e, tuple) and e[0] == "select"],
                             [("select", "button#gobook.submit-circle-button", 1)])
            bad = FakeTab(failure=True)
            self.assertEqual(asyncio.run(one(bad)),
                             "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY")
            self.assertEqual(bad.events.count(("send_keys", "SPACE_KEY")), 1)
            missing = FakeTab(missing=True)
            self.assertEqual(asyncio.run(one(missing)),
                             "SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY")
            self.assertEqual(len([e for e in missing.events if
                                  isinstance(e, tuple) and e[0] == "send_keys"]), 0)

    def test_submission_probe_observes_without_replaying_request(self):
        import ncl_openlab_autobook as module
        arm = module.SUBMIT_PROBE_ARM_JS
        read = module.SUBMIT_PROBE_READ_JS
        self.assertIn('b.addEventListener("click"', arm)
        self.assertIn('e.isTrusted === true', arm)
        self.assertIn('"ajaxSend.nclSubmitProbe"', arm)
        self.assertIn("step2_media[.]jsp", arm)
        self.assertIn("p.click", read)
        self.assertIn("p.ajax", read)
        for forbidden in ("$.post(", "fetch(", "document.cookie",
                          "params.email", "localStorage"):
            self.assertNotIn(forbidden, arm + read)

    def test_bad_pointer_payload_fails_closed(self):
        import ncl_openlab_autobook as module
        class FakeTab:
            async def evaluate(self, code):
                if code == "location.href":
                    return "https://spms.ncl.edu.tw/"
                return {"code": "READY_FOR_POINTER_CLICK",
                        "x": "not a number", "y": 200}

            async def mouse_click(self, x, y):
                raise AssertionError("must not mouse click")
        self.assertEqual(
            asyncio.run(module.submit_once_with_pointer(
                FakeTab(), DAY, SLOT, attempts=1)),
            "INVALID_SUBMIT_COORDINATES")

    def test_entry_selectors_and_consent_are_explicit(self):
        import ncl_openlab_autobook as module
        js = module.ENTRY_JS
        self.assertIn(".art-image.multimedia", js)
        self.assertIn("button#agree-btn.button.agree", js)
        self.assertIn('"AGREEMENT_REQUIRED"', js)
        self.assertIn('if (!action) return "AGREEMENT_REQUIRED"', js)
        self.assertIn('if (location.hostname !== "spms.ncl.edu.tw")', js)
        self.assertNotIn("document.cookie", js)
        self.assertNotIn("fetch(", js)

    def test_entry_does_not_agree_without_opt_in(self):
        import ncl_openlab_autobook as module
        from unittest.mock import patch

        class FakeTab:
            def __init__(self):
                self.scripts = []
            async def evaluate(self, script):
                self.scripts.append(script)
                return "AGREEMENT_REQUIRED"

        async def yes(_):
            return True

        with patch.object(module, "at_official_host", yes):
            tab = FakeTab()
            status = asyncio.run(module.ensure_date_grid(tab))
            self.assertEqual(status, "AGREEMENT_REQUIRED")
            self.assertEqual(len(tab.scripts), 1)
            self.assertIn("const action = false;", tab.scripts[0])

            another = FakeTab()
            status = asyncio.run(module.ensure_date_grid(another, accept_terms=True))
            self.assertEqual(status, "AGREEMENT_REQUIRED")
            self.assertIn("const action = true;", another.scripts[0])

    def test_live_multimedia_status_card_routes_to_date_grid(self):
        """Actual observed path: /NLT/co/multimedia.jsp -> media_discussion.jsp."""
        import ncl_openlab_autobook as module
        js = module.ENTRY_JS
        self.assertIn('location.pathname === "/NLT/co/multimedia.jsp"', js)
        self.assertIn('".lab-item .lab-name[data-zh]"', js)
        # Room name now comes from the profile (ncl_openlab_rooms.json).
        self.assertIn('const roomName = __ROOM_ENTRY_LABEL__;', js)
        self.assertIn('el.getAttribute("data-zh") === roomName', js)
        self.assertIn('const tile = labels[0].closest(".lab-item")', js)
        self.assertIn('tile.click();', js)
        self.assertIn('"STATUS_ROOM_OPENED"', js)
        self.assertIn('"STATUS_ROOM_NOT_UNIQUE"', js)
        self.assertIn('document.querySelectorAll(".date-box").length > 0', js)

    def test_entry_selects_requested_mode_not_another_room(self):
        import ncl_openlab_autobook as module
        from unittest.mock import patch

        class FakeTab:
            def __init__(self):
                self.scripts = []

            async def evaluate(self, script):
                self.scripts.append(script)
                return "STATUS_ROOM_NOT_UNIQUE"

        async def yes(_):
            return True

        with patch.object(module, "at_official_host", yes):
            for mode in ("p03", "music"):
                tab = FakeTab()
                self.assertEqual(asyncio.run(
                    module.ensure_date_grid(tab, mode=mode)),
                    "STATUS_ROOM_NOT_UNIQUE")
                self.assertEqual(len(tab.scripts), 1)
                label = {"music": "音樂創作室", "p03": "個人直播室"}[mode]
                self.assertIn('const roomName = "' + label + '";', tab.scripts[0])

    def test_entry_waits_for_date_grid_after_card_click(self):
        import ncl_openlab_autobook as module
        from unittest.mock import patch

        class FakeTab:
            def __init__(self):
                self.scripts = []
                self.responses = ["STATUS_ROOM_OPENED", "GRID_READY"]

            async def evaluate(self, script):
                self.scripts.append(script)
                return self.responses.pop(0)

        async def yes(_):
            return True

        async def instant_sleep(_):
            return None

        with (patch.object(module, "at_official_host", yes),
              patch.object(module.asyncio, "sleep", instant_sleep)):
            tab = FakeTab()
            self.assertEqual(asyncio.run(
                module.ensure_date_grid(tab, mode="p03")), "GRID_READY")
            self.assertEqual(len(tab.scripts), 2)

    def test_entry_never_clicks_unavailable_room(self):
        import ncl_openlab_autobook as module
        js = module.ENTRY_JS
        self.assertIn('tile.classList.contains("disabled")', js)
        self.assertIn('tile.classList.contains("unavailable")', js)
        self.assertIn('tile.getAttribute("aria-disabled") === "true"', js)
        self.assertIn('"STATUS_ROOM_NOT_ACTIONABLE"', js)

    def test_native_click_requires_one_exact_gobook(self):
        from ncl_openlab_autobook import action_script
        js = action_script("submit", DAY, SLOT)
        self.assertIn('from("button#gobook.submit-circle-button")', js)
        self.assertIn('"SUBMIT_BUTTON_OCCLUDED"', js)
        self.assertIn('window.__nclOneShotSubmit = true', js)
        self.assertNotIn('button.click(); return result("CLICKED_ONCE")', js)

    def test_two_booking_option_requires_two_music_slots_and_authorization(self):
        import contextlib
        from io import StringIO
        from unittest.mock import patch
        import ncl_openlab_autobook as app

        with patch.object(sys, "argv", [
            "app", "--date", "2026-11-12", "--reserve-two",
            "--slots", "13:00-16:00,17:00-20:00"
        ]), contextlib.redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                app.main()
        self.assertEqual(ctx.exception.code, 2)

        with patch.object(sys, "argv", [
            "app", "--date", "2026-11-12", "--room", "p03",
            "--slot", "13:00-14:00", "--auto-submit", "--reserve-two"
        ]), contextlib.redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                app.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_two_booking_cli_passes_exact_order_and_consent(self):
        import contextlib
        from io import StringIO
        from unittest.mock import patch
        import ncl_openlab_autobook as app

        with (patch.object(sys, "argv", [
            "app", "--date", "2026-11-12", "--slots",
            "13:00-16:00,17:00-20:00", "--auto-submit",
            "--reserve-two", "--accept-terms", "--now"
        ]),
              patch.object(app.asyncio, "run", return_value="NOT_RUN") as runner,
              contextlib.redirect_stdout(StringIO())):
            app.main()
        coro = runner.call_args.args[0]
        try:
            vals = coro.cr_frame.f_locals
            self.assertEqual(vals["priorities"], ("13:00-16:00", "17:00-20:00"))
            self.assertTrue(vals["reserve_two"])
            self.assertTrue(vals["accept_terms"])
            self.assertTrue(vals["auto_submit"])
            self.assertEqual(vals["mode"], "music")
        finally:
            coro.close()

    def test_first_booking_failure_stops_second_without_new_navigation(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch
        import types

        class FakeTab:
            def __init__(self):
                self.navigation_count = 0
            async def get(self, _):
                self.navigation_count += 1
                return self

        class FakeBrowser:
            stopped = True
            def __init__(self):
                self.tab = FakeTab()
            async def get(self, _):
                return self.tab
            async def stop(self):
                pass

        fb = FakeBrowser()
        async def fake_start(**kwargs):
            return fb
        async def ready(*args, **kwargs):
            return "GRID_READY"
        async def fake_prompt(*args, **kwargs):
            return ""
        calls = []
        async def book(tab, day, priorities, **kwargs):
            calls.append(priorities)
            return "SUBMITTED_SUCCESS_UNVERIFIED"

        with (patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(start=fake_start)}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", fake_prompt),
              patch.object(app, "book_one_target", book)):
            outcome = asyncio.run(app.autobook(
                date(2026,11,12), ("13:00-16:00", "17:00-20:00"),
                auto_submit=True, now_mode=True, mode="music", reserve_two=True))
        self.assertIn("FIRST_UNVERIFIED_SECOND_NOT_ATTEMPTED", outcome)
        self.assertEqual(calls, [("13:00-16:00",)])
        self.assertEqual(fb.tab.navigation_count, 0)

    def test_verified_first_booking_may_progress_to_second_once(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch
        import types

        class FakeTab:
            def __init__(self):
                self.navigation_count = 0
            async def get(self, _):
                self.navigation_count += 1
                return self

        class FakeBrowser:
            stopped = True
            def __init__(self):
                self.tab = FakeTab()
            async def get(self, _):
                return self.tab
            async def stop(self):
                pass

        fb = FakeBrowser()
        async def fake_start(**kwargs):
            return fb
        async def ready(*args, **kwargs):
            return "GRID_READY"
        async def fake_prompt(*args, **kwargs):
            return ""
        calls = []
        async def book(tab, day, priorities, **kwargs):
            calls.append(priorities)
            return "SUCCESS_PAGE_MATCHED"

        with (patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(start=fake_start)}),
              patch.object(app, "ensure_date_grid", ready),
              patch.object(app.asyncio, "to_thread", fake_prompt),
              patch.object(app, "book_one_target", book)):
            outcome = asyncio.run(app.autobook(
                date(2026,11,12), ("13:00-16:00", "17:00-20:00"),
                auto_submit=True, now_mode=True, mode="music",
                reserve_two=True, accept_terms=True))
        self.assertEqual(outcome, "TWO_BOOKINGS_CONFIRMED")
        self.assertEqual(calls, [("13:00-16:00",), ("17:00-20:00",)])
        self.assertEqual(fb.tab.navigation_count, 1)

    def test_checkout_waits_until_ready_before_one_submit(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        events = []

        class Tab:
            async def evaluate(self, js):
                events.append("checkout_ready")
                return True

        async def stage(tab, phase, *args, **kwargs):
            events.append(phase)
            return "CLICKED"

        async def send(tab, *args, **kwargs):
            events.append("submit")
            return "CLICKED_ONCE"

        async def result(tab, *args, **kwargs):
            return "SUCCESS_PAGE_MATCHED"

        async def nap(seconds):
            events.append(("sleep", seconds))

        with (patch.object(app, "attempt_stage", stage),
              patch.object(app, "submit_once_with_pointer", send),
              patch.object(app, "read_action", result),
              patch.object(app.asyncio, "sleep", nap)):
            status = asyncio.run(app.book_one_target(
                Tab(), DAY, (SLOT,), auto_submit=True))
        self.assertEqual(status, "SUCCESS_PAGE_MATCHED")
        self.assertIn(("sleep", 1.0), events)
        self.assertLess(events.index(("sleep", 1.0)), events.index("submit"))
        self.assertEqual(events.count("submit"), 1)

    def test_checkout_not_ready_never_submits(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        class Tab:
            def __init__(self):
                self.checks = 0

            async def evaluate(self, js):
                self.checks += 1
                return False

        async def stage(tab, phase, *args, **kwargs):
            return "CLICKED"

        async def send(*args, **kwargs):
            raise AssertionError("no final submit when checkout is not ready")

        async def nap(_):
            return None

        tab = Tab()
        with (patch.object(app, "attempt_stage", stage),
              patch.object(app, "submit_once_with_pointer", send),
              patch.object(app.asyncio, "sleep", nap)):
            status = asyncio.run(app.book_one_target(
                tab, DAY, (SLOT,), auto_submit=True))
        self.assertEqual(status, "BLOCKED_CHECKOUT_NOT_READY")
        self.assertEqual(tab.checks, 20)

    def test_release_warmup_and_midnight_refresh_exactly_twice(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        actions = []
        clock = iter((14, 10, 10))

        async def refresh(tab, **kwargs):
            actions.append("refresh")
            return "GRID_READY"

        async def nap(seconds):
            actions.append(("sleep", seconds))

        with (patch.object(app, "seconds_until_release",
                           side_effect=lambda day: next(clock)),
              patch.object(app, "refresh_booking_grid", refresh),
              patch.object(app.asyncio, "sleep", nap)):
            result = asyncio.run(app.wait_until_release(
                object(), DAY, mode="music", accept_terms=False))
        self.assertEqual(result, "GRID_READY")
        self.assertEqual(actions, [("sleep", 4), "refresh",
                                   ("sleep", 10), "refresh"])

    def test_release_skips_warmup_when_too_late(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        actions = []

        async def refresh(*args, **kwargs):
            actions.append("refresh")
            return "GRID_READY"

        async def nap(seconds):
            actions.append(("sleep", seconds))

        with (patch.object(app, "seconds_until_release",
                           side_effect=[2, 2]),
              patch.object(app, "refresh_booking_grid", refresh),
              patch.object(app.asyncio, "sleep", nap)):
            result = asyncio.run(app.wait_until_release(
                object(), DAY, mode="music", accept_terms=False))
        self.assertEqual(result, "GRID_READY")
        self.assertEqual(actions, [("sleep", 2), "refresh"])

    def test_release_early_window_guard_refreshes_nothing(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        async def forbidden(*args, **kwargs):
            raise AssertionError("refresh must not run outside release window")

        with (patch.object(app, "seconds_until_release", return_value=1100),
              patch.object(app, "refresh_booking_grid", forbidden)):
            result = asyncio.run(app.wait_until_release(
                object(), DAY, mode="music", accept_terms=False))
        self.assertEqual(result, "RELEASE_OUTSIDE_15_MINUTE_WINDOW")

    def test_bounded_release_retries_only_unopened_slot_before_submit(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        actions = []
        replies = iter(("NO_BOOKABLE_UI_SLOT", "SUCCESS_PAGE_MATCHED"))

        async def fake_booking(tab, day, priorities, **kwargs):
            actions.append(("attempt", priorities))
            return next(replies)

        async def refresh(*args, **kwargs):
            actions.append("refresh")
            return "GRID_READY"

        async def nap(seconds):
            actions.append(("sleep", seconds))

        with (patch.object(app, "book_one_target", fake_booking),
              patch.object(app, "refresh_booking_grid", refresh),
              patch.object(app.asyncio, "sleep", nap)):
            status = asyncio.run(app.book_with_bounded_retries(
                object(), DAY, (SLOT,), auto_submit=True,
                mode="music", accept_terms=False,
                retry_interval=3, retry_window=20))
        self.assertEqual(status, "SUCCESS_PAGE_MATCHED")
        self.assertEqual(actions, [
            ("attempt", (SLOT,)), ("sleep", 3), "refresh",
            ("attempt", (SLOT,))
        ])

    def test_release_never_retries_after_any_submission_result(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        for result in ("SUCCESS_PAGE_MATCHED", "SUBMITTED_SUCCESS_UNVERIFIED",
                       "BLOCKED_SUBMIT_OUTCOME_UNKNOWN_DO_NOT_RETRY",
                       "BLOCKED_SUMMARY_MISMATCH", "PREVIEW_STOPPED_BEFORE_SUBMIT"):
            calls = []

            async def fake_booking(*args, **kwargs):
                calls.append("attempt")
                return result

            async def forbidden(*args, **kwargs):
                raise AssertionError("no refresh after reaching checkout")

            with (patch.object(app, "book_one_target", fake_booking),
                  patch.object(app, "refresh_booking_grid", forbidden)):
                actual = asyncio.run(app.book_with_bounded_retries(
                    object(), DAY, (SLOT,), auto_submit=True,
                    mode="music", accept_terms=False,
                    retry_interval=3, retry_window=90))
            self.assertEqual(actual, result)
            self.assertEqual(calls, ["attempt"])

    def test_release_mode_uses_short_dom_probes(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        calls = []

        async def probe(tab, phase, day, slot, *, attempts, mode):
            calls.append((phase, attempts))
            return "DATE_NOT_UNIQUE"

        with patch.object(app, "attempt_stage", probe):
            fast = asyncio.run(app.book_one_target(
                object(), DAY, (SLOT,), auto_submit=False, fast_probe=True))
            normal = asyncio.run(app.book_one_target(
                object(), DAY, (SLOT,), auto_submit=False, fast_probe=False))
        self.assertEqual(fast, "BLOCKED_DATE_NOT_UNIQUE")
        self.assertEqual(normal, "BLOCKED_DATE_NOT_UNIQUE")
        self.assertEqual(calls, [("date", 2), ("date", 8)])

    def test_retry_window_zero_stops_without_refresh(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        async def fake_booking(*args, **kwargs):
            return "BLOCKED_DATE_NOT_UNIQUE"

        async def forbidden(*args, **kwargs):
            raise AssertionError("exhausted retry must not refresh")

        with (patch.object(app, "book_one_target", fake_booking),
              patch.object(app, "refresh_booking_grid", forbidden)):
            result = asyncio.run(app.book_with_bounded_retries(
                object(), DAY, (SLOT,), auto_submit=True,
                mode="music", accept_terms=False,
                retry_interval=3, retry_window=0))
        self.assertEqual(result,
                         "RELEASE_WINDOW_EXHAUSTED_BLOCKED_DATE_NOT_UNIQUE")

    def test_slot_priority_and_retry_flags_pass_to_main(self):
        import contextlib
        from io import StringIO
        from unittest.mock import patch
        import ncl_openlab_autobook as app

        with (patch.object(sys, "argv", [
            "app", "--date", "2026-11-12", "--room", "music",
            "--slots", "13:00-16:00,09:00-12:00",
            "--retry-interval", "3", "--retry-window", "90",
            "--auto-submit"
        ]),
              patch.object(app.asyncio, "run", return_value="MOCK") as runner,
              contextlib.redirect_stdout(StringIO())):
            app.main()
        coro = runner.call_args.args[0]
        try:
            self.assertEqual(coro.cr_frame.f_locals["priorities"],
                             ("13:00-16:00", "09:00-12:00"))
            self.assertEqual(coro.cr_frame.f_locals["retry_interval"], 3)
            self.assertEqual(coro.cr_frame.f_locals["retry_window"], 90)
        finally:
            coro.close()

    def test_invalid_retry_frequency_is_rejected_before_browser(self):
        import contextlib
        from io import StringIO
        from unittest.mock import patch
        import ncl_openlab_autobook as app

        with (patch.object(sys, "argv", [
            "app", "--date", "2026-11-12", "--retry-interval", "1"
        ]), contextlib.redirect_stderr(StringIO())):
            with self.assertRaises(SystemExit) as err:
                app.main()
        self.assertEqual(err.exception.code, 2)

    def test_user_manually_closes_browser_for_both_modes(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch
        import types

        for mode, slot in (("music", "13:00-16:00"),
                           ("p03", "13:00-14:00")):
            prompts = []

            class FakeTab:
                pass

            class FakeBrowser:
                stopped = True
                def __init__(self):
                    self.tab = FakeTab()

                async def get(self, url):
                    return self.tab

                async def stop(self):
                    raise AssertionError("automation must not close the browser")

            async def fake_start(**kwargs):
                return FakeBrowser()

            async def ready(*args, **kwargs):
                return "GRID_READY"

            async def reserve(*args, **kwargs):
                return "SUCCESS_PAGE_MATCHED"

            async def fake_prompt(fn, prompt):
                prompts.append(prompt)
                return ""

            with (patch.dict(sys.modules, {
                      "zendriver": types.SimpleNamespace(start=fake_start)}),
                  patch.object(app, "ensure_date_grid", ready),
                  patch.object(app, "book_one_target", reserve),
                  patch.object(app.asyncio, "to_thread", fake_prompt)):
                outcome = asyncio.run(app.autobook(
                    DAY, (slot,), auto_submit=True,
                    now_mode=True, mode=mode))
            self.assertEqual(outcome, "SUCCESS_PAGE_MATCHED")
            self.assertEqual(len(prompts), 1)
            self.assertIn("登入及進入頁面後", prompts[0])

    def test_browser_not_closed_by_program_after_booking_error(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch
        import types

        prompts = []

        class FakeBrowser:
            stopped = True
            async def get(self, url):
                return object()

            async def stop(self):
                raise AssertionError("browser must stay open after an error")

        async def start(**kwargs):
            return FakeBrowser()

        async def blocked(*args, **kwargs):
            return "WRONG_HOST"

        async def prompt(fn, label):
            prompts.append(label)
            return ""

        with (patch.dict(sys.modules, {
                  "zendriver": types.SimpleNamespace(start=start)}),
              patch.object(app, "ensure_date_grid", blocked),
              patch.object(app.asyncio, "to_thread", prompt)):
            with self.assertRaisesRegex(RuntimeError, "DATE_GRID_NOT_READY"):
                asyncio.run(app.autobook(
                    DAY, ("13:00-16:00",), auto_submit=True,
                    now_mode=True, mode="music"))
        self.assertEqual(len(prompts), 1)
        self.assertIn("登入及進入頁面後", prompts[0])

    def test_result_browser_is_kept_open_without_enter_until_user_closes_it(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch
        import types

        checks = []
        sleeps = []

        class Page:
            type_ = "page"

        class Browser:
            stopped = False

            async def _get_targets(self):
                checks.append("poll")
                # The page is still open for two checks. The user then
                # closes all browser windows and three checks see no pages.
                if len(checks) <= 2:
                    return [Page()]
                return []

            async def stop(self):
                raise AssertionError("booking must never close the browser")

        async def nap(seconds):
            sleeps.append(seconds)

        with patch.object(app.asyncio, "sleep", nap):
            asyncio.run(app.wait_until_browser_manually_closed(
                Browser(), interval=0.2))
        self.assertEqual(len(checks), 5)
        self.assertEqual(sleeps, [0.2] * 4)

    def test_result_browser_already_closed_returns_immediately(self):
        import ncl_openlab_autobook as app
        from unittest.mock import patch

        class Browser:
            stopped = True

            async def _get_targets(self):
                raise AssertionError("no browser should be polled after closure")

        async def nap(seconds):
            raise AssertionError("no wait after Chrome already closed")

        with patch.object(app.asyncio, "sleep", nap):
            asyncio.run(app.wait_until_browser_manually_closed(Browser()))

    def test_dom_retry_stops_on_disabled(self):
        class Tab:
            def __init__(self):
                self.calls = 0

        async def fake_read(tab, phase, day, slot):
            tab.calls += 1
            return "SLOT_DISABLED"

        import ncl_openlab_autobook as module
        original = module.read_action
        module.read_action = fake_read
        try:
            tab = Tab()
            self.assertEqual(asyncio.run(attempt_stage(
                tab, "slot", DAY, SLOT, attempts=8)), "SLOT_DISABLED")
            self.assertEqual(tab.calls, 1)
        finally:
            module.read_action = original

    def test_submit_does_not_retry_after_click(self):
        class Tab:
            def __init__(self):
                self.calls = 0

        async def fake_read(tab, phase, day, slot):
            tab.calls += 1
            return "CLICKED_ONCE"

        import ncl_openlab_autobook as module
        original = module.read_action
        module.read_action = fake_read
        try:
            tab = Tab()
            self.assertEqual(asyncio.run(attempt_stage(
                tab, "submit", DAY, SLOT, attempts=8)), "CLICKED_ONCE")
            self.assertEqual(tab.calls, 1)
        finally:
            module.read_action = original


if __name__ == "__main__":
    unittest.main()
