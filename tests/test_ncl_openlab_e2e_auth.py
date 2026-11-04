"""End to end with the REAL engine and a fake browser whose login state follows a timeline.

Real clock, real child processes. Proves: a valid session is reused, the CAPTCHA wait is
detected and confirmed from the page (no button), saved credentials are typed only into
verified fields, an expired session is recovered or the booking is abandoned, rules are
auto-accepted only for versions the user agreed to, and nothing is booked in an unknown
login state. The login page itself is fake: its real DOM is NOT_VERIFIED.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import ncl_openlab_control as ctl
from test_ncl_openlab_e2e_schedule import DAY, Harness, pump_until, soon

SECRET_PW = "pw-secret-9"
GUARD = {"periodic": 1, "lead": 12, "margin": 3, "stop": 11, "min_age": 0}


def plan(*steps):
    return json.dumps([list(s) for s in steps])


class AuthHarness(Harness):
    def __init__(self, test, **env):
        super().__init__(test, **env)
        self.terms_path = self.dir / "terms.json"
        patcher = unittest.mock.patch.dict(os.environ, {"NCL_TERMS_PATH": str(self.terms_path)})
        patcher.start()
        test.addCleanup(patcher.stop)

    def sup(self, **kwargs):
        kwargs.setdefault("auth_check", True)
        return self.supervisor(**kwargs)

    def finish(self, sup, timeout=60):
        self.test.assertTrue(pump_until(sup, lambda: sup.state in ctl.FINAL_STATES, timeout), sup.log)

    def log_text(self, sup):
        return "\n".join(text for _, text in sup.log)


def site_without_login_form(folder):
    """A site config whose login form is not configured (autofill must stay off)."""
    site = json.loads((HERE.parent / "src" / "ncl_openlab_site.json").read_text(encoding="utf-8"))
    site["login"].update(path=None, account_selector=None, password_selector=None,
                         captcha_selector=None, fields=None)
    path = Path(folder) / "site.json"
    path.write_text(json.dumps(site), encoding="utf-8")
    return str(path)


import unittest.mock  # noqa: E402

try:
    import keyring  # noqa: F401
    HAVE_KEYRING = True
except ImportError:
    HAVE_KEYRING = False
NEEDS_KEYRING = unittest.skipUnless(HAVE_KEYRING, "NOT_RUN: keyring package is not installed")


class LoginFlowTests(unittest.TestCase):
    def test_valid_session_is_reused_with_no_login_step_and_no_button(self):
        h = AuthHarness(self)
        run_at = soon(9)
        sup = h.sup(run_at=run_at)
        sup.start()
        self.assertTrue(pump_until(sup, lambda: sup.state == "STANDBY", 20), sup.log)
        self.assertEqual(sup.auth_state, "SESSION_VALID")
        self.assertEqual(h.times("phase"), [])
        h.finish(sup)
        self.assertEqual((sup.state, sup.outcome), ("SUCCESS", "SUCCESS_PAGE_MATCHED"))
        self.assertIn("沿用", h.log_text(sup))
        self.assertGreaterEqual(min(h.times("phase")), run_at.timestamp() - 0.15)
        self.assertEqual((h.times("typed"), h.times("marker")), ([], []))

    def test_captcha_wait_is_detected_and_login_is_confirmed_from_the_page_itself(self):
        login_at = time.time() + 7
        h = AuthHarness(self, NCL_FAKE_SESSION=plan((0, "login"), (login_at, "valid")),
                        NCL_FAKE_GUARD=json.dumps(GUARD))
        run_at = soon(20)
        sup = h.sup(run_at=run_at)
        sup.start()
        self.assertTrue(pump_until(sup, lambda: sup.auth_state == "CAPTCHA_WAITING", 20), sup.log)
        self.assertEqual(sup.state, "LOGIN")
        self.assertFalse(sup.cancel_requested)
        self.assertTrue(pump_until(sup, lambda: sup.state == "STANDBY", 30), sup.log)   # nobody pressed anything
        self.assertEqual(sup.auth_state, "LOGIN_SUCCESS")
        self.assertEqual(h.times("phase"), [])
        h.finish(sup)
        self.assertEqual(sup.state, "SUCCESS")
        text = h.log_text(sup)
        self.assertIn("請在瀏覽器輸入圖片驗證碼並登入", text)
        self.assertIn("登入成功", text)
        self.assertGreaterEqual(min(h.times("phase")), run_at.timestamp() - 0.15)
        self.assertEqual(h.times("typed"), [], "no credentials were saved, nothing is typed")

    @NEEDS_KEYRING
    def test_saved_credentials_are_typed_once_into_verified_fields_and_never_logged(self):
        login_at = time.time() + 8
        h = AuthHarness(self, NCL_FAKE_SESSION=plan((0, "login"), (login_at, "valid")),
                        NCL_FAKE_GUARD=json.dumps(GUARD),
                        NCL_FAKE_CREDS=f"A123456789:{SECRET_PW}")      # default site = inventoried login form
        sup = h.sup(run_at=soon(22), use_saved_login=True)
        sup.start()
        h.finish(sup)
        self.assertEqual(sup.state, "SUCCESS")
        typed = [e for e in h.read() if e["kind"] == "typed"]
        self.assertEqual([(e["field"], e["length"]) for e in typed], [("account", 10), ("password", len(SECRET_PW))])
        self.assertNotIn("captcha", [e["field"] for e in h.read() if e["kind"] in ("typed", "cleared")])
        self.assertEqual(h.times("submit_keypress").__len__(), 1, "only the booking button was pressed")
        everything = h.events.read_text(encoding="utf-8") + h.log_text(sup)
        self.assertNotIn(SECRET_PW, everything)
        self.assertNotIn("A123456789", everything)

    @NEEDS_KEYRING
    def test_unconfigured_login_form_means_the_saved_login_is_not_used(self):
        h = AuthHarness(self, NCL_FAKE_SESSION=plan((0, "login"), (time.time() + 6, "valid")),
                        NCL_FAKE_GUARD=json.dumps(GUARD),
                        NCL_SITE_CONFIG=site_without_login_form(tempfile.mkdtemp()),
                        NCL_FAKE_CREDS=f"A123456789:{SECRET_PW}")
        sup = h.sup(run_at=soon(18), use_saved_login=True)
        sup.start()
        h.finish(sup)
        self.assertEqual(sup.state, "SUCCESS")
        self.assertEqual(h.times("typed"), [])

    @NEEDS_KEYRING
    def test_a_login_page_that_does_not_match_the_inventoried_form_is_never_typed_into(self):
        h = AuthHarness(self, NCL_FAKE_SESSION=plan((0, "login"), (time.time() + 6, "valid")),
                        NCL_FAKE_GUARD=json.dumps(GUARD), NCL_FAKE_FIELDS="bad",
                        NCL_FAKE_CREDS=f"A123456789:{SECRET_PW}")
        sup = h.sup(run_at=soon(18), use_saved_login=True)
        sup.start()
        h.finish(sup)
        self.assertEqual(sup.state, "SUCCESS")          # the human logged in by hand
        self.assertEqual([e for e in h.read() if e["kind"] in ("typed", "cleared")], [])

    def test_cancel_while_waiting_for_the_captcha_books_nothing(self):
        h = AuthHarness(self, NCL_FAKE_SESSION=plan((0, "login")))
        sup = h.sup(run_at=soon(60))
        sup.start()
        self.assertTrue(pump_until(sup, lambda: sup.auth_state == "CAPTCHA_WAITING", 20), sup.log)
        self.assertTrue(sup.cancel())
        h.finish(sup, 20)
        self.assertEqual((sup.state, sup.outcome), ("CANCELLED", "CANCELLED_BEFORE_START"))
        self.assertEqual((h.times("phase"), h.times("reload")), ([], []))
        self.assertFalse(h.lock.exists())

    def test_inconclusive_page_waits_for_the_manual_fallback_button(self):
        h = AuthHarness(self, NCL_FAKE_SESSION=plan((0, "unknown")))
        sup = h.sup(immediate=True)
        sup.start()
        self.assertTrue(pump_until(sup, lambda: sup.auth_state == "AUTH_INTERACTION_REQUIRED", 20), sup.log)
        time.sleep(1.2)
        sup.pump()
        self.assertEqual(h.times("phase"), [], "never proceeds on its own in an unknown login state")
        self.assertTrue(sup.confirm_login())
        h.finish(sup, 30)
        self.assertEqual(sup.state, "SUCCESS")

    def test_manual_fallback_is_ignored_while_the_login_form_is_showing(self):
        h = AuthHarness(self, NCL_FAKE_SESSION=plan((0, "login")))
        sup = h.sup(immediate=True)
        sup.start()
        self.assertTrue(pump_until(sup, lambda: sup.auth_state == "CAPTCHA_WAITING", 20), sup.log)
        sup.confirm_login()
        time.sleep(2.5)
        sup.pump()
        self.assertEqual((sup.state, h.times("phase")), ("LOGIN", []))
        sup.cancel()
        h.finish(sup, 20)


class SessionGuardTests(unittest.TestCase):
    def test_expired_session_is_recovered_by_the_user_and_the_booking_still_starts_on_time(self):
        run_at = soon(34)
        t = run_at.timestamp()
        h = AuthHarness(self, NCL_FAKE_GUARD=json.dumps(GUARD),
                        NCL_FAKE_SESSION=plan((0, "valid"), (t - 24, "login"), (t - 16, "valid")))
        sup = h.sup(run_at=run_at)
        sup.start()
        h.finish(sup, 90)
        self.assertEqual((sup.state, sup.outcome), ("SUCCESS", "SUCCESS_PAGE_MATCHED"))
        text = h.log_text(sup)
        self.assertIn("登入已逾時", text)
        self.assertIn("登入成功", text)
        self.assertGreaterEqual(min(h.times("phase")), t - 0.15)
        self.assertEqual(len(h.times("submit_keypress")), 1)

    def test_expired_and_not_recovered_abandons_the_booking_with_nothing_submitted(self):
        run_at = soon(32)
        t = run_at.timestamp()
        h = AuthHarness(self, NCL_FAKE_GUARD=json.dumps(GUARD),
                        NCL_FAKE_SESSION=plan((0, "valid"), (t - 22, "login")))
        sup = h.sup(run_at=run_at)
        sup.start()
        h.finish(sup, 90)
        self.assertEqual((sup.state, sup.outcome), ("FAILED", "SESSION_EXPIRED_NOT_RECOVERED"))
        self.assertEqual((h.times("phase"), h.times("submit_keypress")), ([], []))
        self.assertLess(max([e["t"] for e in h.read()]), t + 0.5, "gave up before the start time")
        self.assertIn("登入已逾時", h.log_text(sup))

    def test_login_lost_exactly_at_the_warmup_stops_with_a_session_expired_outcome(self):
        run_at = soon(14)
        t = run_at.timestamp()
        h = AuthHarness(self, NCL_FAKE_SESSION=plan((0, "valid"), (t - 12, "login")),
                        NCL_FAKE_ENTRY_AFTER_RELOAD="ENTRY_NOT_FOUND_OR_AMBIGUOUS")
        sup = h.sup(run_at=run_at)
        sup.start()
        h.finish(sup, 60)
        self.assertEqual(sup.state, "FAILED")
        self.assertIn("SESSION_EXPIRED", sup.outcome)
        self.assertEqual((h.times("phase"), h.times("submit_keypress")), ([], []))


class TermsFlowTests(unittest.TestCase):
    def run_terms(self, version, *, agree_in=5, accept=True, terms_path=None):
        h = AuthHarness(self, NCL_FAKE_TERMS=version, NCL_FAKE_AGREE_AT=str(time.time() + agree_in))
        if terms_path:
            h.terms_path = Path(terms_path)
            unittest.mock.patch.dict(os.environ, {"NCL_TERMS_PATH": str(terms_path)}).start()
        sup = h.sup(immediate=True, accept_terms=accept)
        sup.start()
        h.finish(sup, 40)
        return h, sup

    def test_first_encounter_needs_the_user_then_the_same_version_is_accepted_automatically(self):
        folder = tempfile.mkdtemp()
        terms_file = Path(folder) / "terms.json"
        h1, sup1 = self.run_terms("abc123def", terms_path=terms_file)
        self.assertEqual(sup1.state, "SUCCESS")
        self.assertIn("同意", h1.log_text(sup1))
        self.assertEqual([e["kind"] for e in h1.read() if e["kind"].startswith("agree")], ["agree_manual"])
        self.assertEqual(json.loads(terms_file.read_text(encoding="utf-8")), {"versions": ["abc123def"]})
        h2, sup2 = self.run_terms("abc123def", agree_in=999, terms_path=terms_file)   # nobody to click
        self.assertEqual(sup2.state, "SUCCESS")
        self.assertEqual([e["kind"] for e in h2.read() if e["kind"].startswith("agree")], ["agree_click"])

    def test_changed_rules_ask_for_consent_again(self):
        folder = tempfile.mkdtemp()
        terms_file = Path(folder) / "terms.json"
        self.run_terms("abc123def", terms_path=terms_file)
        h, sup = self.run_terms("f00dbabe99", agree_in=4, terms_path=terms_file)
        self.assertEqual([e["kind"] for e in h.read() if e["kind"].startswith("agree")], ["agree_manual"])
        self.assertIn("同意", h.log_text(sup))
        self.assertEqual(json.loads(terms_file.read_text(encoding="utf-8"))["versions"],
                         ["abc123def", "f00dbabe99"])

    def test_auto_accept_is_off_unless_the_user_enabled_it(self):
        folder = tempfile.mkdtemp()
        terms_file = Path(folder) / "terms.json"
        self.run_terms("abc123def", terms_path=terms_file)
        h, sup = self.run_terms("abc123def", agree_in=4, accept=False, terms_path=terms_file)
        self.assertEqual([e["kind"] for e in h.read() if e["kind"].startswith("agree")], ["agree_manual"])


if __name__ == "__main__":
    unittest.main()
