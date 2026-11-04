#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Login/session state machine for the NCL booking engine (shared by GUI and CLI).

What it does:  detect an existing session and reuse it; otherwise wait while the
user types the picture CAPTCHA and logs in; optionally type the saved account and
password into the official form first; confirm success from several signals; keep
watching the session while the schedule waits.

What it never does: read, guess, recognise or fill the CAPTCHA; press the login
button; retry a login on its own more than once; keep a session alive by polling;
read or report cookies, tokens, names or page text. Page probes return booleans.
"""
import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from ncl_openlab_schedule import TAIPEI_TZ, SystemClock

NCL_HOST = "spms.ncl.edu.tw"
SITE_CONFIG = Path(__file__).with_name("ncl_openlab_site.json")
AUTH_STATES = ("SESSION_VALID", "LOGIN_REQUIRED", "CAPTCHA_WAITING", "LOGIN_VERIFYING",
               "LOGIN_SUCCESS", "SESSION_EXPIRED", "AUTH_FAILED", "AUTH_INTERACTION_REQUIRED")
AUTH_LABELS = {
    "SESSION_VALID": "已偵測到有效登入，沿用中", "LOGIN_REQUIRED": "需要登入",
    "CAPTCHA_WAITING": "請在瀏覽器輸入圖片驗證碼並登入", "LOGIN_VERIFYING": "確認登入狀態中",
    "LOGIN_SUCCESS": "登入成功（已確認）", "SESSION_EXPIRED": "登入已逾時，需要重新驗證",
    "AUTH_FAILED": "登入失敗，已停止（避免鎖定帳號）",
    "AUTH_INTERACTION_REQUIRED": "需要你在瀏覽器處理（無法自動判斷）",
}
CHECK_LEAD = 300.0       # one real session check this long before the start
PERIODIC = 60.0          # DOM-only probe interval while on standby (no requests)
RECOVER_MARGIN = 30.0    # a human re-login must be finished this long before the start
STOP_GUARD_AT = 12.0     # hand over to the T-10 warm-up
REAL_CHECK_MIN_AGE = 120.0
LOGIN_TIMEOUT = 600.0
POLL = 1.0
MAX_FAILED_ROUNDS = 2
MAX_PROBE_ERRORS = 5
_SELECTOR_OK = re.compile(r"^[A-Za-z0-9_\-.#\[\]=\"' :]{1,80}$")
_HASH_OK = re.compile(r"^[0-9a-f]{6,16}$")

# ------------------------------------------------------------------ page scripts
_COMMON_JS = r"""
  const clean = (el) => String(el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden";
  };
"""

SESSION_PROBE_JS = r"""(() => {
  const cfg = __CFG__;
  __COMMON__
  if (location.hostname !== "spms.ncl.edu.tw") return {host: "OTHER"};
  const items = Array.from(document.querySelectorAll("a, button, li, div, span, [role='button']"))
    .filter(visible);
  const hasLabel = (label) => items.some(el => clean(el) === label);
  const welcome = items.some(el => { const t = clean(el); return t.startsWith(cfg.welcome) && t.length <= 40; });
  return {
    host: "NCL", path: location.pathname.slice(0, 60),
    logout: hasLabel(cfg.logout), records: hasLabel(cfg.records), welcome: welcome,
    password_fields: Array.from(document.querySelectorAll("input[type='password']")).filter(visible).length,
    agree_dialog: Array.from(document.querySelectorAll("button#agree-btn.button.agree")).filter(visible).length > 0,
    date_grid: document.querySelectorAll(".date-box").length > 0,
    login_marker: window.__nclLoginMarker === true
  };
})()"""

MARK_LOGIN_JS = "(() => { window.__nclLoginMarker = true; return true; })()"

FIELD_CHECK_JS = r"""(() => {
  const sel = __SELECTORS__;
  __COMMON__
  const find = (s) => Array.from(document.querySelectorAll(s)).filter(visible);
  const account = find(sel.account), password = find(sel.password);
  const one = account.length === 1 && password.length === 1;
  return {
    account: account.length, password: password.length,
    password_type: one && password[0].type === "password",
    account_type_ok: one && ["text", "tel", "email", "number", ""].includes(account[0].type),
    same_form: one && !!account[0].form && account[0].form === password[0].form,
    captcha_safe: one && account[0] !== password[0]
  };
})()"""

TERMS_JS = r"""(() => {
  const marker = __MARKER__;
  __COMMON__
  const cyrb53 = (str) => {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) {
      const ch = str.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761); h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16);
  };
  const agree = Array.from(document.querySelectorAll("button#agree-btn.button.agree")).filter(visible);
  if (agree.length !== 1) return {present: false, hash: null};
  let node = agree[0];
  for (let i = 0; i < 10 && node; i++, node = node.parentElement)
    if (clean(node).includes(marker)) return {present: true, hash: cyrb53(clean(node))};
  return {present: true, hash: null};
})()"""

# Structure only: never values, never image sources, never cookies.
LOGIN_PROBE_JS = r"""(() => {
  __COMMON__
  if (location.hostname !== "spms.ncl.edu.tw") return {host: "OTHER"};
  const forms = Array.from(document.forms);
  const field = (el) => ({
    tag: "input", type: String(el.type || "").slice(0, 20), name: String(el.name || "").slice(0, 40),
    id: String(el.id || "").slice(0, 40), autocomplete: String(el.autocomplete || "").slice(0, 20),
    maxlength: el.maxLength > 0 ? el.maxLength : null,
    placeholder: String(el.placeholder || "").slice(0, 30), form: forms.indexOf(el.form)});
  return {
    host: "NCL", path: location.pathname.slice(0, 60),
    inputs: Array.from(document.querySelectorAll("input")).filter(visible)
      .filter(el => !["hidden", "checkbox", "radio"].includes(el.type)).slice(0, 12).map(field),
    forms: forms.map((f, i) => ({index: i, method: String(f.method || "").slice(0, 6),
      action_path: (() => { try { return new URL(f.action, location.href).pathname.slice(0, 60); } catch (e) { return ""; } })(),
      images: Array.from(f.querySelectorAll("img")).filter(visible).length,
      buttons: Array.from(f.querySelectorAll("button, input[type='submit'], input[type='button']"))
        .filter(visible).slice(0, 4).map(b => clean(b).slice(0, 12))})).slice(0, 4)
  };
})()"""


def _script(template, **values):
    out = template.replace("__COMMON__", _COMMON_JS)
    for key, value in values.items():
        out = out.replace(f"__{key}__", json.dumps(value, ensure_ascii=False))
    return out


# ------------------------------------------------------------------ site config
class SiteConfigError(ValueError):
    pass


def load_site(path=None):
    """Validated site facts. Unknown login selectors stay None (manual login)."""
    try:
        data = json.loads(Path(path or os.environ.get("NCL_SITE_CONFIG") or SITE_CONFIG)
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SiteConfigError(f"cannot read site config: {exc}") from None
    try:
        session, terms, login = data["session"], data["terms"], data["login"]
        for key in ("logout_label", "records_label", "welcome_prefix"):
            if not isinstance(session[key], str) or not session[key].strip():
                raise SiteConfigError(f"session.{key} is empty")
        if not isinstance(terms["marker_text"], str) or not terms["marker_text"].strip():
            raise SiteConfigError("terms.marker_text is empty")
        for key in ("account_selector", "password_selector"):
            value = login[key]
            if value is not None and (not isinstance(value, str) or not _SELECTOR_OK.match(value)):
                raise SiteConfigError(f"login.{key} is not a plain selector")
    except (KeyError, TypeError):
        raise SiteConfigError("site config is missing a section") from None
    return data


def autofill_available(site):
    login = site["login"]
    return bool(login["account_selector"] and login["password_selector"])


# --------------------------------------------------------------------- probing
def validate_probe(raw):
    if not isinstance(raw, dict) or raw.get("host") not in ("NCL", "OTHER"):
        return None
    if raw["host"] == "OTHER":
        return {"host": "OTHER"}
    flags = ("logout", "records", "welcome", "agree_dialog", "date_grid", "login_marker")
    if not all(isinstance(raw.get(k), bool) for k in flags):
        return None
    count = raw.get("password_fields")
    if type(count) is not int or not 0 <= count <= 20:
        return None
    return {"host": "NCL", "path": str(raw.get("path", ""))[:60], "password_fields": count,
            **{k: raw[k] for k in flags}}


def classify_probe(raw):
    """SESSION_VALID | LOGIN_REQUIRED | OFF_SITE | UNKNOWN. Several signals, never one."""
    data = validate_probe(raw)
    if data is None:
        return "UNKNOWN"
    if data["host"] == "OTHER":
        return "OFF_SITE"
    if data["password_fields"] > 0:
        return "LOGIN_REQUIRED"
    if data["logout"] and (data["records"] or data["welcome"]):
        return "SESSION_VALID"
    return "UNKNOWN"


def probe_script(site):
    session = site["session"]
    return _script(SESSION_PROBE_JS, CFG={"logout": session["logout_label"],
                                          "records": session["records_label"],
                                          "welcome": session["welcome_prefix"]})


async def probe_state(tab, site=None):
    """One read-only classification; a dead tab or odd result is UNKNOWN, never a guess."""
    try:
        return classify_probe(await tab.evaluate(probe_script(site or load_site())))
    except Exception:
        return "UNKNOWN"


# ----------------------------------------------------------------- terms consent
class TermsConsent:
    """Hashes of rules versions the user personally agreed to. No text is stored."""

    def __init__(self, path):
        self.path, self.pending = Path(path), None

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [h for h in data.get("versions", []) if isinstance(h, str) and _HASH_OK.match(h)]
        except (OSError, ValueError, AttributeError):
            return []

    def is_consented(self, version):
        return bool(version) and version in self._read()

    def record(self, version):
        if not version or not _HASH_OK.match(str(version)):
            return False
        versions = self._read()
        if version not in versions:
            versions.append(version)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"versions": versions[-20:]}), encoding="utf-8")
        return True


def validate_terms(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("present"), bool):
        return None
    version = raw.get("hash")
    if version is not None and not (isinstance(version, str) and _HASH_OK.match(version)):
        return None
    return {"present": raw["present"], "hash": version}


# --------------------------------------------------------------- authenticator
class Authenticator:
    """Drives the eight auth states. Time, cancel and emit are injected for testing."""

    def __init__(self, tab, *, site=None, clock=None, cancelled=None, confirmed=None,
                 emit=None, credentials=None, timeout=LOGIN_TIMEOUT, poll=POLL, log=print):
        self.tab, self.site = tab, site or load_site()
        self.clock = clock or SystemClock()
        self.cancelled = cancelled or (lambda: False)
        self.confirmed = confirmed or (lambda: False)
        self.emit, self.credentials = emit or (lambda state, detail: None), credentials
        self.timeout, self.poll, self.log = timeout, poll, log
        self.state, self.history, self._errors, self._last = None, [], 0, None

    def _set(self, state, detail=""):
        """Emit only real changes (state or explanatory text), never a repeat."""
        if (state, detail) == self._last:
            return
        self._last = (state, detail)
        changed = state != self.state
        self.state = state
        if changed:
            self.history.append(state)
            self.log(f"登入狀態：{state}")
        self.emit(state, detail or AUTH_LABELS[state])

    async def probe_once(self):
        try:
            result = classify_probe(await self.tab.evaluate(probe_script(self.site)))
            self._errors = 0
            return result
        except Exception:
            self._errors += 1
            return "UNKNOWN"

    @property
    def browser_gone(self):
        return self._errors >= MAX_PROBE_ERRORS

    async def settled(self, polls=2, limit=6):
        """The same answer twice in a row, so a page that is still loading is not misread."""
        previous, seen = None, 0
        for _ in range(limit):
            state = await self.probe_once()
            seen = seen + 1 if state == previous else 1
            previous = state
            if seen >= polls:
                return state
            await self.clock.sleep(self.poll)
        return "UNKNOWN"

    async def autofill(self):
        """Type the saved account and password into the verified fields. Never the CAPTCHA,
        never the login button. Returns True only if both fields were filled."""
        login = self.site["login"]
        if not autofill_available(self.site):
            self.log("登入頁欄位尚未實機確認，請手動登入")
            return False
        creds = self.credentials() if self.credentials else None
        if not creds:
            return False
        selectors = {"account": login["account_selector"], "password": login["password_selector"]}
        try:
            check = await self.tab.evaluate(_script(FIELD_CHECK_JS, SELECTORS=selectors))
            if not (isinstance(check, dict) and check.get("account") == 1 and check.get("password") == 1
                    and check.get("password_type") is True and check.get("account_type_ok") is True
                    and check.get("same_form") is True):
                self.log("登入欄位不唯一或型別不符，不自動填入")
                return False
            account_el = await self.tab.select(selectors["account"], timeout=2)
            password_el = await self.tab.select(selectors["password"], timeout=2)
            if account_el is None or password_el is None:
                return False
            await account_el.clear_input()
            await account_el.send_keys(creds[0])
            await password_el.clear_input()
            await password_el.send_keys(creds[1])
        except Exception as exc:
            self.log(f"自動填入失敗（{type(exc).__name__}），請手動登入")
            return False
        finally:
            creds = None
        return True

    async def _stable_success(self):
        """After the first valid reading, require it again a moment later."""
        for _ in range(2):
            await self.clock.sleep(self.poll)
            if await self.probe_once() != "SESSION_VALID":
                return False
        return True

    async def ensure(self, *, deadline=None, reason="start"):
        """None when a verified session exists, otherwise a stable outcome code."""
        self._set("LOGIN_VERIFYING")
        state = await self.settled()
        if state == "SESSION_VALID":
            self._set("SESSION_VALID")
            return None
        self._set("SESSION_EXPIRED" if reason == "expired" else "LOGIN_REQUIRED")
        if state == "LOGIN_REQUIRED" and self.credentials is not None:
            await self.autofill()        # at most once per ensure(): no blind retry loop
        started, failures, marked = self.clock.now(), 0, False
        self._set("CAPTCHA_WAITING" if state == "LOGIN_REQUIRED" else "AUTH_INTERACTION_REQUIRED")
        while True:
            if self.cancelled():
                return "CANCELLED_BEFORE_START"
            now = self.clock.now()
            if deadline is not None and now >= deadline:
                return "AUTH_NOT_COMPLETED_BEFORE_START"
            if (now - started).total_seconds() > self.timeout:
                self._set("AUTH_INTERACTION_REQUIRED", "等待逾時，已停止；未收到登入完成")
                return "AUTH_NO_RESPONSE"
            await self.clock.sleep(self.poll)
            state = await self.probe_once()
            if self.browser_gone:
                return "BROWSER_UNREACHABLE"
            if state == "LOGIN_REQUIRED":
                data = await self._marker_lost() if marked else False
                if data:                 # the form came back after a submit round trip
                    failures += 1
                    marked = False
                    if failures >= MAX_FAILED_ROUNDS:
                        self._set("AUTH_FAILED")
                        return "AUTH_FAILED"
                    self._set("CAPTCHA_WAITING", "驗證碼或密碼可能錯誤，請重新輸入")
                if not marked:
                    marked = await self._mark()
                continue
            if state == "SESSION_VALID" or (state == "UNKNOWN" and self.confirmed()
                                            and await self._manual_ok()):
                self._set("LOGIN_VERIFYING")
                if state != "SESSION_VALID" or await self._stable_success():
                    self._set("LOGIN_SUCCESS")
                    return None
                continue
            if state in ("UNKNOWN", "OFF_SITE"):
                self._set("AUTH_INTERACTION_REQUIRED")

    async def _manual_ok(self):
        """Human override for inconclusive pages: official host and no password field."""
        try:
            data = validate_probe(await self.tab.evaluate(probe_script(self.site)))
        except Exception:
            return False
        return bool(data and data["host"] == "NCL" and data["password_fields"] == 0)

    async def _mark(self):
        try:
            return bool(await self.tab.evaluate(MARK_LOGIN_JS))
        except Exception:
            return False

    async def _marker_lost(self):
        try:
            data = validate_probe(await self.tab.evaluate(probe_script(self.site)))
        except Exception:
            return False
        return bool(data and data["host"] == "NCL" and data["password_fields"] > 0
                    and not data["login_marker"])


# ----------------------------------------------------------------- standby guard
async def standby_guard(auth, timeline, *, real_check, reenter, lead=None, periodic=None,
                        margin=None, stop_at=None):
    """Watch the session while the schedule waits. None = go on; else an outcome code.

    - every ``periodic`` seconds: DOM-only probe (no request); only a visible login
      form or an off-site redirect counts as expired, an unknown page is ignored
    - once, about ``lead`` seconds before the start: one real check (reload) unless
      the session was verified for real very recently
    - an expired session may be re-verified by the user until ``margin`` seconds
      before the start; after that the booking is abandoned, not attempted blind
    """
    lead = CHECK_LEAD if lead is None else lead
    periodic = PERIODIC if periodic is None else periodic
    margin = RECOVER_MARGIN if margin is None else margin
    stop_at = STOP_GUARD_AT if stop_at is None else stop_at
    clock = timeline.clock
    state = {"last_real": clock.now(), "did_main": timeline.remaining() <= lead}

    async def recover():
        code = await auth.ensure(deadline=timeline.run_at - timedelta(seconds=margin),
                                 reason="expired")
        if code == "AUTH_NOT_COMPLETED_BEFORE_START":
            return "SESSION_EXPIRED_NOT_RECOVERED"
        if code:
            return code
        status = await reenter()
        if status != "GRID_READY":
            return "REENTRY_BLOCKED_" + str(status)
        state["last_real"] = clock.now()
        return None

    while True:
        remaining = timeline.remaining()
        if remaining <= stop_at:
            return None
        if not state["did_main"] and remaining <= lead:
            state["did_main"] = True
            if (clock.now() - state["last_real"]).total_seconds() > REAL_CHECK_MIN_AGE:
                status = await real_check()
                if status == "SESSION_EXPIRED":
                    auth._set("SESSION_EXPIRED")
                    outcome = await recover()
                    if outcome:
                        return outcome
                elif status != "GRID_READY":
                    return "SESSION_CHECK_BLOCKED_" + str(status)
                else:
                    state["last_real"] = clock.now()
            continue
        if await auth.probe_once() in ("LOGIN_REQUIRED", "OFF_SITE"):
            auth._set("SESSION_EXPIRED")
            outcome = await recover()
            if outcome:
                return outcome
            continue
        if auth.browser_gone:
            return "BROWSER_UNREACHABLE"
        step = min(periodic, remaining - stop_at)
        if not state["did_main"]:
            step = min(step, remaining - lead)
        await timeline.sleep(max(step, 1.0))


# --------------------------------------------------------------- login DOM probe
async def probe_login_page(report_dir):
    """Read-only inventory of the LOGIN page structure, for filling ncl_openlab_site.json."""
    from ncl_openlab_browser import start_browser
    from ncl_openlab_probe import NCL_URL
    import zendriver as uc

    browser = await start_browser(uc)
    try:
        tab = await browser.get(NCL_URL)
        print("請在瀏覽器自行開啟「登入頁」（先不要登入，也不要輸入任何資料）。")
        await asyncio.to_thread(input, "登入頁顯示後按 Enter 擷取欄位結構：")
        raw = await tab.evaluate(_script(LOGIN_PROBE_JS))
        folder = Path(report_dir)
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / ("ncl_login_probe_" + datetime.now(TAIPEI_TZ).strftime("%Y%m%d_%H%M%S") + ".json")
        out.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已輸出：{out}（只含欄位型別與名稱，沒有任何輸入值、圖片來源或 Cookie）")
        print("依此結果填入 src/ncl_openlab_site.json 的 login 兩個 selector，並實機驗證後才會啟用自動填入。")
    finally:
        print("請自行關閉瀏覽器。")


def main():
    parser = argparse.ArgumentParser(description="國圖登入頁唯讀探測")
    parser.add_argument("--probe-login", action="store_true", required=True)
    parser.add_argument("--report-dir", default="ncl_reports")
    args = parser.parse_args()
    asyncio.run(probe_login_page(args.report_dir))


if __name__ == "__main__":
    main()
