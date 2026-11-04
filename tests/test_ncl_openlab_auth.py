"""Auth state machine, session guard and terms consent with fake clocks and mock tabs.

Nothing here touches a real site: every login page is a scripted fake, so a pass
proves the logic, not the live login page (reported as NOT_VERIFIED for the site).
"""
import asyncio
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import ncl_openlab_auth as au
import ncl_openlab_autobook as app
from ncl_fakes import AuthTab, HookedClock, good_field_check, probe
from ncl_openlab_schedule import TAIPEI_TZ, Timeline

T0 = datetime(2026, 11, 5, 0, 0, 0, tzinfo=TAIPEI_TZ)
SITE = au.load_site()
FILLABLE = SITE        # the real, inventoried login form structure
NULL_SITE = {**SITE, "login": {**SITE["login"], "path": None, "account_selector": None,
                               "password_selector": None, "captcha_selector": None, "fields": None}}


def run(coro):
    return asyncio.run(coro)


def make(state="valid", *, site=None, credentials=None, timeout=600, **kw):
    clock = HookedClock(T0 - timedelta(hours=1))
    tab = AuthTab(clock, state)
    events = []
    auth = au.Authenticator(tab, site=site or SITE, clock=clock, emit=lambda s, d: events.append((s, d)),
                            credentials=credentials, timeout=timeout, log=lambda *a: None, **kw)
    return clock, tab, auth, events


class ClassifyTests(unittest.TestCase):
    def test_one_signal_is_never_enough(self):
        cases = {
            "logout only": ({"logout": True}, "UNKNOWN"),
            "records only": ({"records": True}, "UNKNOWN"),
            "welcome only": ({"welcome": True}, "UNKNOWN"),
            "records+welcome without logout": ({"records": True, "welcome": True}, "UNKNOWN"),
            "logout+records": ({"logout": True, "records": True}, "SESSION_VALID"),
            "logout+welcome": ({"logout": True, "welcome": True}, "SESSION_VALID"),
            "everything but a password field is present": ({"logout": True, "records": True,
                                                            "password_fields": 1}, "LOGIN_REQUIRED"),
            "nothing": ({}, "UNKNOWN"),
        }
        for name, (flags, expected) in cases.items():
            self.assertEqual(au.classify_probe(probe("none", **flags)), expected, name)

    def test_url_alone_decides_nothing(self):
        # a /NLT/ path with no header is still unknown; a login-looking path with a header is valid
        self.assertEqual(au.classify_probe(probe("none", path="/NLT/co/multimedia.jsp")), "UNKNOWN")
        self.assertEqual(au.classify_probe(probe("valid", path="/login.jsp")), "SESSION_VALID")

    def test_off_site_and_malformed_results(self):
        self.assertEqual(au.classify_probe(probe("offsite")), "OFF_SITE")
        for bad in (None, [], "x", {}, {"host": "EVIL"}, probe("valid", logout="yes"),
                    probe("valid", password_fields=-1), probe("valid", password_fields=True)):
            self.assertEqual(au.classify_probe(bad), "UNKNOWN", bad)

    def test_validated_probe_has_no_free_text(self):
        data = au.validate_probe(probe("valid", path="/" + "x" * 500, name="秘密", cookie="abc"))
        self.assertLessEqual(len(data["path"]), 60)
        self.assertNotIn("name", data)
        self.assertNotIn("cookie", data)
        self.assertTrue(all(isinstance(v, (bool, int, str)) for v in data.values()))

    def test_probe_scripts_read_nothing_sensitive(self):
        for script in (au.probe_script(SITE), au.MARK_LOGIN_JS, au._script(au.LOGIN_PROBE_JS),
                       au._script(au.TERMS_JS, MARKER="x"),
                       au._script(au.FIELD_CHECK_JS, SELECTORS={"account": "#a", "password": "#p"})):
            for forbidden in ("document.cookie", "localStorage", "sessionStorage", "fetch(", "XMLHttpRequest",
                              ".value", ".src", "click()", "submit("):
                self.assertNotIn(forbidden, script, forbidden)


class SiteConfigTests(unittest.TestCase):
    def test_default_config_carries_the_inventoried_login_form(self):
        login = SITE["login"]
        self.assertEqual(login["status"], "DOM_VERIFIED")
        self.assertEqual(login["path"], "/NLT/co/login.jsp")
        self.assertEqual((login["account_selector"], login["password_selector"], login["captcha_selector"]),
                         ("input#name", "input#password", "input#insrand"))
        self.assertEqual({k: (v["id"], v["name"]) for k, v in login["fields"].items()},
                         {"account": ("name", "name"), "password": ("password", "psword"),
                          "captcha": ("insrand", "insrand")})
        self.assertEqual(login["fields"]["account"]["types"], ["password", "text"])   # account is type=password
        self.assertEqual(login["fields"]["password"]["types"], ["password"])
        self.assertEqual(login["fields"]["captcha"]["types"], ["text"])
        self.assertTrue(au.autofill_available(SITE))
        self.assertFalse(au.autofill_available(NULL_SITE))

    def test_bad_selectors_and_sections_are_refused(self):
        for selector in ("input, button", "a > b", "x" * 200, "", 5, "<script>"):
            data = json.loads(json.dumps(SITE))
            data["login"]["account_selector"] = selector
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "s.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(au.SiteConfigError, msg=repr(selector)):
                    au.load_site(path)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text('{"schema_version": 1}', encoding="utf-8")
            with self.assertRaises(au.SiteConfigError):
                au.load_site(path)


class LoginConfigValidationTests(unittest.TestCase):
    def load(self, mutate):
        data = json.loads(json.dumps(SITE))
        mutate(data["login"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return au.load_site(path)

    def assertRefused(self, mutate, label):
        with self.assertRaises(au.SiteConfigError, msg=label):
            self.load(mutate)

    def test_inconsistent_login_blocks_are_refused(self):
        def swap_ids(login):
            login["fields"]["password"]["id"] = login["fields"]["account"]["id"]
        cases = {
            "missing captcha selector": lambda l: l.update(captcha_selector=None),
            "missing path": lambda l: l.update(path=None),
            "relative path": lambda l: l.update(path="login.jsp"),
            "path with query": lambda l: l.update(path="/a?x=1"),
            "duplicate selectors": lambda l: l.update(captcha_selector=l["account_selector"]),
            "missing fields": lambda l: l.update(fields=None),
            "extra role": lambda l: l["fields"].update(extra={"id": "x", "name": "x", "types": ["text"]}),
            "same id twice": swap_ids,
            "password field not a password type": lambda l: l["fields"]["password"].update(types=["text"]),
            "password field also allowing text": lambda l: l["fields"]["password"].update(types=["password", "text"]),
            "captcha as password": lambda l: l["fields"]["captcha"].update(types=["password"]),
            "unknown input type": lambda l: l["fields"]["account"].update(types=["file"]),
            "bad id": lambda l: l["fields"]["account"].update(id="a b"),
            "script in selector": lambda l: l.update(account_selector="<script>"),
        }
        for label, mutate in cases.items():
            self.assertRefused(mutate, label)

    def test_fully_null_login_block_is_accepted_as_unconfigured(self):
        site = self.load(lambda l: l.update(path=None, account_selector=None, password_selector=None,
                                            captcha_selector=None, fields=None))
        self.assertFalse(au.autofill_available(site))

    def test_account_type_password_is_allowed_only_through_the_config_list(self):
        site = self.load(lambda l: l["fields"]["account"].update(types=["text"]))
        self.assertEqual(site["login"]["fields"]["account"]["types"], ["text"])


class EnsureTests(unittest.TestCase):
    def test_a_valid_session_is_reused_without_touching_the_login_form(self):
        called = []
        clock, tab, auth, events = make("valid", site=FILLABLE, credentials=lambda: called.append(1))
        self.assertIsNone(run(auth.ensure()))
        self.assertEqual(auth.history, ["LOGIN_VERIFYING", "SESSION_VALID"])
        self.assertEqual((called, tab.typed, tab.count("marker")), ([], [], 0))

    def test_not_logged_in_waits_for_the_human_and_confirms_from_the_page(self):
        clock, tab, auth, events = make("login")
        clock.at(95, lambda: setattr(tab, "state", "valid"))
        self.assertIsNone(run(auth.ensure()))
        self.assertEqual(auth.history, ["LOGIN_VERIFYING", "LOGIN_REQUIRED", "CAPTCHA_WAITING",
                                        "LOGIN_VERIFYING", "LOGIN_SUCCESS"])
        self.assertEqual(tab.typed, [])
        self.assertGreaterEqual(clock.elapsed(), 95)

    def test_success_needs_a_stable_reading_not_a_single_flash(self):
        clock, tab, auth, events = make("login")
        clock.at(10, lambda: setattr(tab, "state", "valid"))
        clock.at(11.5, lambda: setattr(tab, "state", "login"))      # bounced back to login
        clock.at(40, lambda: setattr(tab, "state", "valid"))
        self.assertIsNone(run(auth.ensure()))
        self.assertGreaterEqual(clock.elapsed(), 40)
        self.assertEqual(auth.history.count("LOGIN_SUCCESS"), 1)

    def test_a_loading_page_is_not_misread_as_logged_out(self):
        clock, tab, auth, _ = make("none")
        clock.at(1.5, lambda: setattr(tab, "state", "valid"))
        self.assertIsNone(run(auth.ensure()))
        self.assertNotIn("CAPTCHA_WAITING", auth.history)

    def test_every_state_name_is_defined_and_labelled(self):
        self.assertEqual(set(au.AUTH_LABELS), set(au.AUTH_STATES))
        self.assertEqual(len(au.AUTH_STATES), 8)

    def test_nobody_answers_stops_safely_without_guessing(self):
        clock, tab, auth, events = make("login", timeout=120)
        self.assertEqual(run(auth.ensure()), "AUTH_NO_RESPONSE")
        self.assertEqual(auth.state, "AUTH_INTERACTION_REQUIRED")
        self.assertEqual(tab.typed, [])
        self.assertLess(clock.elapsed(), 130)

    def test_deadline_before_verification_aborts(self):
        clock, tab, auth, _ = make("login")
        self.assertEqual(run(auth.ensure(deadline=clock.now() + timedelta(seconds=40))),
                         "AUTH_NOT_COMPLETED_BEFORE_START")

    def test_cancel_while_waiting_for_the_captcha(self):
        flag = {"stop": False}
        clock, tab, auth, _ = make("login", cancelled=lambda: flag["stop"])
        clock.at(20, lambda: flag.update(stop=True))
        self.assertEqual(run(auth.ensure()), "CANCELLED_BEFORE_START")

    def test_two_failed_rounds_stop_instead_of_hammering_the_login(self):
        clock, tab, auth, events = make("login", site=FILLABLE, credentials=lambda: ("acct", "pw-secret"))
        for offset in (30, 60):
            clock.at(offset, lambda: setattr(tab, "marker", False))   # form came back after a submit
        self.assertEqual(run(auth.ensure()), "AUTH_FAILED")
        self.assertEqual(auth.state, "AUTH_FAILED")
        self.assertEqual([t for t, _ in tab.typed], ["account", "password"], "typed exactly once")
        self.assertTrue(any("可能錯誤" in detail for _, detail in events))

    def test_a_browser_that_stops_answering_is_reported(self):
        clock, tab, auth, _ = make("login")
        clock.at(10, lambda: setattr(tab, "probe_error", True))
        self.assertEqual(run(auth.ensure()), "BROWSER_UNREACHABLE")

    def test_inconclusive_page_needs_the_human_and_the_manual_override_is_guarded(self):
        flag = {"ok": False}
        clock, tab, auth, _ = make("none", confirmed=lambda: flag["ok"])
        clock.at(30, lambda: flag.update(ok=True))
        self.assertIsNone(run(auth.ensure()))
        self.assertIn("AUTH_INTERACTION_REQUIRED", auth.history)
        # the override is ignored while a password field is on screen
        clock, tab, auth, _ = make("login", confirmed=lambda: True, timeout=30)
        self.assertEqual(run(auth.ensure()), "AUTH_NO_RESPONSE")
        # and refused off the official site
        clock, tab, auth, _ = make("offsite", confirmed=lambda: True, timeout=30)
        self.assertEqual(run(auth.ensure()), "AUTH_NO_RESPONSE")

    def test_manual_override_rechecks_the_page_and_loses_a_race_with_the_login_form(self):
        """Page looked inconclusive at the first probe, then the login form appeared."""
        clock, tab, auth, _ = make("none", confirmed=lambda: True, timeout=20)
        real = tab.evaluate
        seen = {"probes": 0}

        async def flipping(script):
            if "password_fields" in script and "logout" in script:
                seen["probes"] += 1
                tab.state = "none" if seen["probes"] % 2 else "login"    # alternates per probe
            return await real(script)
        tab.evaluate = flipping
        self.assertNotEqual(run(auth.ensure()), None)
        self.assertNotIn("LOGIN_SUCCESS", auth.history)

    def test_expired_reason_uses_the_expired_state_first(self):
        clock, tab, auth, _ = make("login")
        clock.at(30, lambda: setattr(tab, "state", "valid"))
        self.assertIsNone(run(auth.ensure(reason="expired")))
        self.assertEqual(auth.history[:3], ["LOGIN_VERIFYING", "SESSION_EXPIRED", "CAPTCHA_WAITING"])


class AutofillTests(unittest.TestCase):
    CREDS = ("A123456789", "pw-secret-123")

    def test_account_and_password_are_typed_once_into_their_own_fields_only(self):
        clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda: self.CREDS)
        clock.at(60, lambda: setattr(tab, "state", "valid"))
        self.assertIsNone(run(auth.ensure()))
        self.assertEqual(tab.typed, [("account", self.CREDS[0]), ("password", self.CREDS[1])])
        self.assertNotIn("captcha", [kind for kind, _ in tab.typed])
        self.assertEqual(tab.count("click"), 0, "the login button is never pressed")

    def test_unverified_login_dom_means_no_typing_even_with_saved_credentials(self):
        loaded = []
        clock, tab, auth, _ = make("login", site=NULL_SITE, credentials=lambda: loaded.append(1) or self.CREDS)
        clock.at(30, lambda: setattr(tab, "state", "valid"))
        self.assertIsNone(run(auth.ensure()))
        self.assertEqual((tab.typed, loaded), ([], []), "credentials are not even read")

    def broken(self, **change):
        check = good_field_check()
        for key, value in change.items():
            if key == "counts":
                check["counts"] = {**check["counts"], **value}
            else:
                check[key] = value
        return check

    def test_every_structural_mismatch_refuses_to_fill(self):
        bad_checks = {
            "wrong path": self.broken(path_ok=False),
            "wrong host": self.broken(host_ok=False),
            "two account fields": self.broken(counts={"account": 2}),
            "no password field": self.broken(counts={"password": 0}),
            "CAPTCHA field missing": self.broken(counts={"captcha": 0}),
            "CAPTCHA field duplicated": self.broken(counts={"captcha": 2}),
            "hidden duplicate (mixed visibility)": self.broken(counts={"account": -1}),
            "same element for two roles": self.broken(distinct=False),
            "different forms": self.broken(same_form=False),
            "id or name differs": self.broken(attrs_ok=False),
            "type not allowed": self.broken(types_ok=False),
            "missing keys": {"host_ok": True, "path_ok": True},
            "legacy shape": {"account": 1, "password": 1, "password_type": True},
            "none": None, "garbage": "garbage", "list": [],
        }
        for name, check in bad_checks.items():
            clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda: self.CREDS, timeout=20)
            tab.field_check = check
            self.assertEqual(run(auth.ensure()), "AUTH_NO_RESPONSE", name)
            self.assertEqual(tab.typed, [], name)

    def test_the_verified_structure_is_accepted_even_though_the_account_field_is_a_password_type(self):
        self.assertTrue(au.fields_verified(good_field_check()))
        self.assertIn("password", SITE["login"]["fields"]["account"]["types"])
        clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda: self.CREDS, timeout=20)
        self.assertEqual(run(auth.ensure()), "AUTH_NO_RESPONSE")     # nobody typed the CAPTCHA
        self.assertEqual([k for k, _ in tab.typed], ["account", "password"])

    def test_the_captcha_field_is_never_selected_typed_or_clicked(self):
        selected = []
        clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda: self.CREDS, timeout=15)
        real = tab.select

        async def spying(selector, timeout=10):
            selected.append(selector)
            return await real(selector, timeout)
        tab.select = spying
        run(auth.ensure())
        self.assertNotIn("input#insrand", selected)
        self.assertEqual(sorted(selected), ["input#name", "input#password"])
        self.assertNotIn("captcha", [k for k, _ in tab.typed])
        self.assertEqual([e for e in tab.log if e[0] == "click"], [])

    def test_a_wrong_element_is_not_typed_into_even_if_the_page_check_passed(self):
        from ncl_fakes import Typing
        for selector, impostor in (("input#name", "captcha"), ("input#password", "captcha"),
                                   ("input#name", "password"), ("input#password", "account")):
            clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda: self.CREDS, timeout=15)
            tab.select_override[selector] = Typing(tab, impostor)
            run(auth.ensure())
            self.assertEqual(tab.typed, [], (selector, impostor))

    def test_the_same_element_for_both_selectors_is_refused(self):
        from ncl_fakes import Typing
        clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda: self.CREDS, timeout=15)
        shared = Typing(tab, "password")
        tab.select_override.update({"input#name": shared, "input#password": shared})
        run(auth.ensure())
        self.assertEqual(tab.typed, [])

    def test_credentials_with_control_characters_are_refused_so_enter_is_never_sent(self):
        for creds in (("A123456789", "pw\n"), ("A1\r", "pw"), ("", "pw"), ("A1", ""), ("A1", None)):
            clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda c=creds: c, timeout=10)
            run(auth.ensure())
            self.assertEqual(tab.typed, [], creds)

    def test_a_page_that_stops_matching_between_check_and_typing_is_not_typed_into(self):
        clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda: self.CREDS, timeout=10)
        tab.select_override["input#password"] = None        # element vanished
        run(auth.ensure())
        self.assertEqual(tab.typed, [], "nothing typed when either field cannot be selected")

    def test_no_saved_credentials_means_manual_login(self):
        clock, tab, auth, _ = make("login", site=FILLABLE, credentials=lambda: None, timeout=20)
        self.assertEqual(run(auth.ensure()), "AUTH_NO_RESPONSE")
        self.assertEqual(tab.typed, [])

    def test_the_password_never_reaches_logs_or_emitted_states(self):
        logs = []
        clock = HookedClock(T0 - timedelta(hours=1))
        tab = AuthTab(clock, "login")
        events = []
        auth = au.Authenticator(tab, site=FILLABLE, clock=clock, emit=lambda s, d: events.append((s, d)),
                                credentials=lambda: self.CREDS, log=logs.append, timeout=10)
        run(auth.ensure())
        blob = json.dumps([logs, events, [e for e in tab.log if e[0] != "type"]], ensure_ascii=False)
        self.assertNotIn(self.CREDS[1], blob)
        self.assertNotIn(self.CREDS[0], blob)


class TermsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = au.TermsConsent(Path(self.tmp.name) / "terms.json")
        self.clock = HookedClock(T0)

    def grid(self, tab, accept, store=None):
        return run(app.ensure_date_grid(tab, accept_terms=accept, mode="p03", terms=store or self.store))

    def tab(self, version):
        tab = AuthTab(self.clock)
        tab.terms = {"present": True, "hash": version}
        tab.dialog = True
        return tab

    def test_unseen_version_is_not_auto_accepted_then_remembered_after_the_user_agrees(self):
        tab = self.tab("abc123def")
        self.assertEqual(self.grid(tab, accept=True), "AGREEMENT_REQUIRED")
        self.assertEqual(tab.count("entry"), 1)
        self.assertEqual([e[1] for e in tab.log if e[0] == "entry"], [False])
        self.assertFalse(self.store.is_consented("abc123def"))
        tab.terms = {"present": False, "hash": None}      # the user clicked "同意" themselves
        tab.agreed = True
        self.store.pending = "abc123def"
        self.assertEqual(self.grid(tab, accept=True), "GRID_READY")
        self.assertTrue(self.store.is_consented("abc123def"))

    def test_consented_version_is_accepted_automatically_only_when_enabled(self):
        self.store.record("abc123def")
        tab = self.tab("abc123def")
        self.assertEqual(self.grid(tab, accept=False), "AGREEMENT_REQUIRED")      # option off
        self.assertEqual(self.grid(self.tab("abc123def"), accept=True), "GRID_READY")
        tab2 = self.tab("abc123def")
        self.grid(tab2, accept=True)
        self.assertEqual([e[1] for e in tab2.log if e[0] == "entry"][:1], [True])

    def test_changed_terms_require_fresh_consent(self):
        self.store.record("0ldversion1")
        tab = self.tab("n3wversion2")
        self.assertEqual(self.grid(tab, accept=True), "AGREEMENT_REQUIRED")
        self.assertFalse(self.store.is_consented("n3wversion2"))

    def test_unreadable_dialog_is_never_auto_accepted(self):
        for hashed in (None, "NOT HEX!", ""):
            tab = self.tab(hashed)
            tab.terms = {"present": True, "hash": hashed}
            self.assertEqual(self.grid(tab, accept=True), "AGREEMENT_REQUIRED", hashed)
        tab = self.tab("abc123def")
        tab.terms = "garbage"
        self.assertEqual(self.grid(tab, accept=True), "AGREEMENT_REQUIRED")

    def test_store_keeps_hashes_only_and_ignores_junk(self):
        self.assertFalse(self.store.record("not hex"))
        self.assertFalse(self.store.record(None))
        self.store.record("abc123def")
        data = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(data, {"versions": ["abc123def"]})
        self.store.path.write_text("garbage", encoding="utf-8")
        self.assertFalse(self.store.is_consented("abc123def"))

    def test_without_a_store_the_legacy_behaviour_is_unchanged(self):
        tab = AuthTab(self.clock)
        self.assertEqual(run(app.ensure_date_grid(tab, accept_terms=True, mode="p03")), "GRID_READY")
        self.assertEqual([e[1] for e in tab.log if e[0] == "entry"], [True])


class GuardHarness:
    def __init__(self, remaining, *, state="valid", **auth_kw):
        self.clock = HookedClock(T0 - timedelta(seconds=remaining))
        self.tab = AuthTab(self.clock, state)
        self.events = []
        self.auth = au.Authenticator(self.tab, site=SITE, clock=self.clock, timeout=3600,
                                     emit=lambda s, d: self.events.append(s), log=lambda *a: None, **auth_kw)
        self.timeline = Timeline(T0, self.clock)
        self.reenter_calls = []

    async def real_check(self):
        return await app.refresh_booking_grid(self.tab, mode="p03", accept_terms=False)

    async def reenter(self):
        self.reenter_calls.append(self.clock.now())
        return "GRID_READY"

    def go(self):
        return run(au.standby_guard(self.auth, self.timeline, real_check=self.real_check,
                                    reenter=self.reenter))


class StandbyGuardTests(unittest.TestCase):
    def test_healthy_session_gets_cheap_probes_and_exactly_one_real_check(self):
        h = GuardHarness(900)
        self.assertIsNone(h.go())
        self.assertEqual(h.tab.count("reload"), 1, "one real check, not continuous refreshing")
        reload_at = [e[1] for e in h.tab.log if e[0] == "reload"][0]
        self.assertAlmostEqual((T0 - reload_at).total_seconds(), 300, delta=2)
        self.assertGreaterEqual(h.tab.count("probe"), 10)
        self.assertLessEqual(h.tab.count("probe"), 20, "low frequency (about once a minute)")
        self.assertEqual(h.tab.typed, [])
        self.assertAlmostEqual(h.timeline.remaining(), au.STOP_GUARD_AT, delta=2)

    def test_started_late_does_not_add_a_pointless_reload(self):
        h = GuardHarness(150)       # verified moments ago, less than the 5 minute mark away
        self.assertIsNone(h.go())
        self.assertEqual(h.tab.count("reload"), 0)

    def test_too_close_to_the_start_the_guard_stays_out_of_the_way(self):
        h = GuardHarness(8)
        self.assertIsNone(h.go())
        self.assertEqual(h.clock.sleeps, [])

    def test_expiry_seen_by_a_periodic_probe_is_recovered_by_the_user(self):
        h = GuardHarness(900)
        h.clock.at(300, lambda: setattr(h.tab, "state", "login"))
        h.clock.at(480, lambda: setattr(h.tab, "state", "valid"))
        self.assertIsNone(h.go())
        self.assertIn("SESSION_EXPIRED", h.events)
        self.assertIn("CAPTCHA_WAITING", h.events)
        self.assertEqual(h.events[-1], "LOGIN_SUCCESS")
        self.assertEqual(len(h.reenter_calls), 1)

    def test_not_recovered_before_the_start_abandons_the_booking(self):
        h = GuardHarness(600)
        h.clock.at(100, lambda: setattr(h.tab, "state", "login"))
        self.assertEqual(h.go(), "SESSION_EXPIRED_NOT_RECOVERED")
        self.assertAlmostEqual(h.timeline.remaining(), au.RECOVER_MARGIN, delta=3)
        self.assertEqual(h.reenter_calls, [])

    def test_a_recovery_after_the_margin_is_too_late(self):
        h = GuardHarness(600)
        h.clock.at(100, lambda: setattr(h.tab, "state", "login"))
        h.clock.at(600 - 20, lambda: setattr(h.tab, "state", "valid"))     # 20 s before: inside margin
        self.assertEqual(h.go(), "SESSION_EXPIRED_NOT_RECOVERED")

    def test_real_check_that_lands_on_the_login_page_triggers_recovery(self):
        h = GuardHarness(900)
        real = h.real_check

        async def expired_check():
            h.tab.state = "login"          # the reload revealed the login page
            h.tab.entry = "ENTRY_NOT_FOUND_OR_AMBIGUOUS"
            result = await real()
            h.clock.at(h.clock.elapsed() + 40, lambda: (setattr(h.tab, "state", "valid"),
                                                          setattr(h.tab, "entry", "GRID_READY")))
            return result
        h.real_check = expired_check
        self.assertIsNone(h.go())
        self.assertIn("SESSION_EXPIRED", h.events)
        self.assertEqual(len(h.reenter_calls), 1)

    def test_unknown_pages_do_not_cause_false_expiry(self):
        h = GuardHarness(900)
        h.clock.at(100, lambda: setattr(h.tab, "state", "none"))      # header not recognised
        self.assertIsNone(h.go())
        self.assertNotIn("SESSION_EXPIRED", h.events)

    def test_network_down_at_the_real_check_stops_with_a_clear_code(self):
        h = GuardHarness(900)
        h.tab.reload_error = OSError("offline")
        self.assertEqual(h.go(), "SESSION_CHECK_BLOCKED_REFRESH_FAILED_OSError")

    def test_redirect_to_another_host_counts_as_expired(self):
        h = GuardHarness(600)
        h.clock.at(100, lambda: setattr(h.tab, "state", "offsite"))
        h.clock.at(160, lambda: setattr(h.tab, "state", "valid"))
        self.assertIsNone(h.go())
        self.assertIn("SESSION_EXPIRED", h.events)

    def test_cancel_during_the_guard_propagates(self):
        flag = {"stop": False}
        h = GuardHarness(900)
        h.timeline = Timeline(T0, h.clock, cancelled=lambda: flag["stop"])
        h.clock.at(120, lambda: flag.update(stop=True))
        from ncl_openlab_schedule import ScheduleCancelled
        with self.assertRaises(ScheduleCancelled):
            h.go()

    def test_sleeping_through_the_start_is_reported_by_the_timeline(self):
        h = GuardHarness(900)
        h.clock.jumps = {5: 3600}
        from ncl_openlab_schedule import ScheduleMissed
        with self.assertRaises(ScheduleMissed):
            h.go()

    def test_refresh_after_t_minus_10_reports_session_expired_not_a_generic_block(self):
        clock = HookedClock(T0 - timedelta(seconds=60))
        tab = AuthTab(clock, "login", entry="ENTRY_NOT_FOUND_OR_AMBIGUOUS")
        timeline = Timeline(T0, clock)
        status = run(app.wait_until_release(tab, date(2026, 11, 12), mode="p03", accept_terms=False,
                                            timeline=timeline, max_wait_seconds=86400))
        self.assertEqual(status, "PRE_REFRESH_BLOCKED_SESSION_EXPIRED")
        self.assertEqual(tab.count("reload"), 1, "no booking attempt after a failed warm-up")


if __name__ == "__main__":
    unittest.main()
