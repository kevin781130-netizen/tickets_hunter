"""The session/terms/login probe scripts run for real in headless Chromium on fake NCL pages.

Pages are synthetic (modelled on the user's screenshots). They prove the scripts read only
booleans and structure; they do NOT prove the live login page looks like this (NOT_VERIFIED).
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import ncl_browser as browser
import ncl_openlab_auth as au
from ncl_fakes import probe  # noqa: F401  (shared shape)

SITE = au.load_site()
PERSON = "歡迎～林O甲"
HOME = "https://spms.ncl.edu.tw/NLT/co/index.jsp"
RULES = ("1.本中心空間及設施設備之線上預約或現場登記限本人持借閱證預約登記。"
         "2.請遵守各空間及設施設備之使用說明。3.基於安全考量，請遵守各空間適用年齡建議。是否同意以上規範？")

HEADER = ('<div class="top"><a>空間現況</a><a>我的紀錄</a><a>登出</a><a>English</a>'
          f'<span>{PERSON}</span></div>')
TILES = '<div class="art-image multimedia"></div><div>多媒體創意實驗中心</div>'


def dialog(text=RULES):
    return (f'<div class="modal"><div class="box"><p>{text}</p>'
            '<button class="button" id="disagree">不同意 Disagree</button>'
            '<button id="agree-btn" class="button agree">同意 Agree</button></div></div>')


def page(body):
    return f"<!doctype html><meta charset='utf-8'><body>{body}</body>"


LOGGED_IN = page(HEADER + TILES)
WITH_DIALOG = page(HEADER + TILES + dialog())
def login_form(*, account='<input type="password" id="name" name="name" value="A123456789" maxlength="10">',
               password='<input type="password" id="password" name="psword" value="TopSecretPw">',
               captcha='<input type="text" id="insrand" name="insrand" value="ZK7Q" maxlength="4">',
               extra="", split_captcha=False, header=True):
    top = '<div class="top"><a>空間現況</a><a>English</a></div>' if header else ""
    first = account + password + ("" if split_captcha else captcha)
    second = f"<form id='f2'>{captcha}</form>" if split_captcha else ""
    return page(top + '<form id="f" method="post" action="/NLT/login.do?token=SECRET_TOKEN">' + first +
                '<img src="/captcha.jpg?session=SESSION_ABC" width="80" height="30">'
                '<input type="hidden" name="csrf" value="HIDDEN_CSRF">'
                '<button type="submit">登入</button></form>' + second + extra)


LOGIN = login_form()
LOGIN_URL = "https://spms.ncl.edu.tw/NLT/co/login.jsp"
LOGGED_OUT_HOME = page('<div class="top"><a>空間現況</a><a>English</a></div>' + TILES)
OTHER_SITE = "https://other.example/login"


@unittest.skipUnless(browser.available(), "NOT_VERIFIED: headless Chromium unavailable")
class ProbeDomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        site_probe = au.probe_script(SITE)
        field_check = au._script(au.FIELD_CHECK_JS, LOGIN=SITE["login"])
        loose = {**SITE["login"], "account_selector": "input"}
        bad_check = au._script(au.FIELD_CHECK_JS, LOGIN=loose)
        terms = au._script(au.TERMS_JS, MARKER=SITE["terms"]["marker_text"])
        cases = [
            {"id": "in", "html": LOGGED_IN, "url": HOME, "steps": [{"js": site_probe}]},
            {"id": "login", "html": LOGIN, "url": LOGIN_URL,
             "steps": [{"js": site_probe}, {"js": field_check}, {"js": bad_check},
                       {"js": au._script(au.LOGIN_PROBE_JS)}, {"js": au.MARK_LOGIN_JS}, {"js": site_probe}]},
            {"id": "out", "html": LOGGED_OUT_HOME, "url": HOME, "steps": [{"js": site_probe}]},
            {"id": "other", "html": LOGIN, "url": OTHER_SITE, "steps": [{"js": site_probe}]},
            {"id": "dialog", "html": WITH_DIALOG, "url": HOME, "steps": [{"js": terms}, {"js": site_probe}]},
            {"id": "dialog2", "html": page(HEADER + TILES + dialog(RULES + " 新增條款第4點。")),
             "url": HOME, "steps": [{"js": terms}]},
            {"id": "dialog_same", "html": WITH_DIALOG, "url": HOME, "steps": [{"js": terms}]},
            {"id": "no_marker", "html": page(HEADER + dialog("完全不同的文字")), "url": HOME,
             "steps": [{"js": terms}]},
            {"id": "nodialog", "html": LOGGED_IN, "url": HOME, "steps": [{"js": terms}]},
            {"id": "only_logout", "html": page('<div class="top"><a>登出</a></div>'), "url": HOME,
             "steps": [{"js": site_probe}]},
        ]
        cls.results = browser.run_cases(cases)

    def steps(self, case_id):
        result = self.results[case_id]
        self.assertIsNone(result["error"], result["error"])
        return result["steps"]

    def test_logged_in_page_is_recognised_from_several_signals(self):
        raw = self.steps("in")[0]
        self.assertEqual(au.classify_probe(raw), "SESSION_VALID")
        self.assertTrue(raw["logout"] and raw["records"] and raw["welcome"])

    def test_probe_returns_only_booleans_and_a_short_path_never_the_name(self):
        for case, index in (("in", 0), ("login", 0), ("dialog", 1), ("out", 0)):
            raw = self.steps(case)[index]
            self.assertTrue(all(isinstance(v, (bool, int)) or k in ("path", "host") for k, v in raw.items()))
            self.assertNotIn("林", json.dumps(raw, ensure_ascii=False))
            self.assertNotIn("SECRET", json.dumps(raw))

    def test_login_page_logged_out_page_and_foreign_host(self):
        self.assertEqual(au.classify_probe(self.steps("login")[0]), "LOGIN_REQUIRED")
        self.assertEqual(au.classify_probe(self.steps("out")[0]), "UNKNOWN")
        self.assertEqual(au.classify_probe(self.steps("other")[0]), "OFF_SITE")
        self.assertEqual(au.classify_probe(self.steps("only_logout")[0]), "UNKNOWN")

    def test_rules_dialog_hash_is_stable_changes_with_content_and_is_null_if_unreadable(self):
        first = au.validate_terms(self.steps("dialog")[0])
        again = au.validate_terms(self.steps("dialog_same")[0])
        changed = au.validate_terms(self.steps("dialog2")[0])
        self.assertTrue(first["present"] and first["hash"])
        self.assertEqual(first["hash"], again["hash"])
        self.assertNotEqual(first["hash"], changed["hash"])
        self.assertEqual(au.validate_terms(self.steps("no_marker")[0]), {"present": True, "hash": None})
        self.assertEqual(au.validate_terms(self.steps("nodialog")[0]), {"present": False, "hash": None})

    def test_dialog_over_a_logged_in_page_still_reads_as_logged_in(self):
        raw = self.steps("dialog")[1]
        self.assertEqual(au.classify_probe(raw), "SESSION_VALID")
        self.assertTrue(raw["agree_dialog"])

    def test_real_login_form_passes_even_though_the_account_field_is_a_password_type(self):
        good = self.steps("login")[1]
        self.assertTrue(au.fields_verified(good), good)
        self.assertEqual(good["counts"], {"account": 1, "password": 1, "captcha": 1})
        self.assertTrue(good["host_ok"] and good["path_ok"] and good["distinct"] and good["same_form"]
                        and good["attrs_ok"] and good["types_ok"])

    def test_a_loose_selector_that_matches_several_inputs_is_refused(self):
        self.assertFalse(au.fields_verified(self.steps("login")[2]))
        self.assertNotEqual(self.steps("login")[2]["counts"]["account"], 1)

    def test_login_structure_probe_leaks_no_values_tokens_or_image_sources(self):
        raw = self.steps("login")[3]
        text = json.dumps(raw, ensure_ascii=False)
        for secret in ("A123456789", "TopSecretPw", "ZK7Q", "HIDDEN_CSRF", "SESSION_ABC", "SECRET_TOKEN"):
            self.assertNotIn(secret, text)
        types = [i["type"] for i in raw["inputs"]]
        self.assertEqual(sorted(types), ["password", "password", "text"])
        self.assertEqual(raw["forms"][0]["images"], 1)          # a picture next to the form (CAPTCHA)
        self.assertEqual(raw["forms"][0]["action_path"], "/NLT/login.do")

    def test_login_marker_is_set_and_visible_to_the_next_probe(self):
        self.assertFalse(self.steps("login")[0]["login_marker"])
        self.assertTrue(self.steps("login")[5]["login_marker"])


def check_case(case_id, html, url=LOGIN_URL, login=None):
    script = au._script(au.FIELD_CHECK_JS, LOGIN=login or SITE["login"])
    return {"id": case_id, "html": html, "url": url, "steps": [{"js": script}]}


FIELD_CASES = {
    # name: (html, url, expected verdict)
    "normal": (login_form(), LOGIN_URL, True),
    "normal with a query string": (login_form(), LOGIN_URL + "?from=home", True),
    "account field type text": (login_form(account='<input type="text" id="name" name="name">'), LOGIN_URL, True),
    "wrong path (same form on another page)": (login_form(), "https://spms.ncl.edu.tw/NLT/co/index.jsp", False),
    "wrong path (look-alike)": (login_form(), "https://spms.ncl.edu.tw/NLT/co/login.jsp.evil", False),
    "wrong host": (login_form(), "https://other.example/NLT/co/login.jsp", False),
    "error page without the form": (page("<h1>系統忙碌，請稍後再試</h1>"), LOGIN_URL, False),
    "form without the CAPTCHA field": (login_form(captcha=""), LOGIN_URL, False),
    "duplicate CAPTCHA field": (login_form(extra='<form><input type="text" id="insrand" name="insrand"></form>'),
                                LOGIN_URL, False),
    "duplicate account id": (login_form(extra='<form><input type="password" id="name" name="name"></form>'),
                             LOGIN_URL, False),
    "hidden duplicate of the account field": (login_form(
        extra='<input type="password" id="name" name="name" style="display:none">'), LOGIN_URL, False),
    "account field type not allowed": (login_form(account='<input type="email" id="name" name="name">'),
                                       LOGIN_URL, False),
    "password field is plain text": (login_form(password='<input type="text" id="password" name="psword">'),
                                     LOGIN_URL, False),
    "CAPTCHA field turned into a password input": (
        login_form(captcha='<input type="password" id="insrand" name="insrand">'), LOGIN_URL, False),
    "DOM order reversed (identity is id+name, not position)": (login_form(
        account='<input type="password" id="password" name="psword">',
        password='<input type="password" id="name" name="name">'), LOGIN_URL, True),
    "id of one field with the name of another": (login_form(
        account='<input type="password" id="name" name="psword">',
        password='<input type="password" id="password" name="name">'), LOGIN_URL, False),
    "right ids, wrong name attributes": (login_form(
        account='<input type="password" id="name" name="psword">',
        password='<input type="password" id="password" name="name">'), LOGIN_URL, False),
    "CAPTCHA input carrying the account name": (login_form(
        captcha='<input type="text" id="insrand" name="name">'), LOGIN_URL, False),
    "CAPTCHA in a different form": (login_form(split_captcha=True), LOGIN_URL, False),
    "inputs outside any form": (page('<input type="password" id="name" name="name">'
                                     '<input type="password" id="password" name="psword">'
                                     '<input type="text" id="insrand" name="insrand">'), LOGIN_URL, False),
}


@unittest.skipUnless(browser.available(), "NOT_VERIFIED: headless Chromium unavailable")
class LoginFormCheckTests(unittest.TestCase):
    """FIELD_CHECK_JS against the real login structure and every confusing variant."""

    @classmethod
    def setUpClass(cls):
        cls.results = browser.run_cases([check_case(name, html, url)
                                         for name, (html, url, _) in FIELD_CASES.items()])

    def test_only_the_exact_official_form_is_accepted(self):
        for name, (_, _, expected) in FIELD_CASES.items():
            result = self.results[name]
            self.assertIsNone(result["error"], f"{name}: {result['error']}")
            self.assertEqual(au.fields_verified(result["steps"][0]), expected, f"{name}: {result['steps'][0]}")

    def test_the_check_reads_structure_only_never_values(self):
        text = json.dumps(self.results["normal"]["steps"][0])
        for secret in ("A123456789", "TopSecretPw", "ZK7Q", "SESSION_ABC", "HIDDEN_CSRF"):
            self.assertNotIn(secret, text)
        self.assertTrue(all(isinstance(v, (bool, dict)) for v in self.results["normal"]["steps"][0].values()))


if __name__ == "__main__":
    unittest.main()
