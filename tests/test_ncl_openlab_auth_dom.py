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
LOGIN = page('<div class="top"><a>空間現況</a><a>English</a></div>'
             '<form id="f" method="post" action="/NLT/login.do?token=SECRET_TOKEN">'
             '<input type="text" name="uid" id="uid" value="A123456789" maxlength="10" placeholder="閱覽證號">'
             '<input type="password" name="pwd" id="pwd" value="TopSecretPw">'
             '<input type="text" name="captcha" id="cap" value="ZK7Q" maxlength="4">'
             '<img src="/captcha.jpg?session=SESSION_ABC" width="80" height="30">'
             '<input type="hidden" name="csrf" value="HIDDEN_CSRF">'
             '<button type="submit">登入</button></form>')
LOGGED_OUT_HOME = page('<div class="top"><a>空間現況</a><a>English</a></div>' + TILES)
OTHER_SITE = "https://other.example/login"


@unittest.skipUnless(browser.available(), "NOT_VERIFIED: headless Chromium unavailable")
class ProbeDomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        site_probe = au.probe_script(SITE)
        field_check = au._script(au.FIELD_CHECK_JS, SELECTORS={"account": "#uid", "password": "#pwd"})
        bad_check = au._script(au.FIELD_CHECK_JS, SELECTORS={"account": "input", "password": "#pwd"})
        terms = au._script(au.TERMS_JS, MARKER=SITE["terms"]["marker_text"])
        cases = [
            {"id": "in", "html": LOGGED_IN, "url": HOME, "steps": [{"js": site_probe}]},
            {"id": "login", "html": LOGIN, "url": "https://spms.ncl.edu.tw/NLT/login.jsp",
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

    def test_field_check_accepts_only_exactly_one_account_and_password_field(self):
        good, bad = self.steps("login")[1], self.steps("login")[2]
        self.assertEqual((good["account"], good["password"], good["password_type"],
                          good["account_type_ok"], good["same_form"]), (1, 1, True, True, True))
        self.assertGreater(bad["account"], 1, "a loose selector matches several inputs -> refused")

    def test_login_structure_probe_leaks_no_values_tokens_or_image_sources(self):
        raw = self.steps("login")[3]
        text = json.dumps(raw, ensure_ascii=False)
        for secret in ("A123456789", "TopSecretPw", "ZK7Q", "HIDDEN_CSRF", "SESSION_ABC", "SECRET_TOKEN"):
            self.assertNotIn(secret, text)
        types = [i["type"] for i in raw["inputs"]]
        self.assertEqual(sorted(types), ["password", "text", "text"])
        self.assertEqual(raw["forms"][0]["images"], 1)          # a picture next to the form (CAPTCHA)
        self.assertEqual(raw["forms"][0]["action_path"], "/NLT/login.do")

    def test_login_marker_is_set_and_visible_to_the_next_probe(self):
        self.assertFalse(self.steps("login")[0]["login_marker"])
        self.assertTrue(self.steps("login")[5]["login_marker"])


if __name__ == "__main__":
    unittest.main()
