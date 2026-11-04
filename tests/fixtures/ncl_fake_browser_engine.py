"""The REAL engine (autobook.main) driving a fake zendriver. No network, no Chrome.

Every page action is appended with a wall-clock timestamp to $NCL_FAKE_EVENTS so
tests can assert WHEN the booking operations started and what was done.
Scenario via $NCL_FAKE_RESULT: success (default) | unverified | failure.
"""
import json
import os
import re
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
EVENTS = os.environ["NCL_FAKE_EVENTS"]
RESULT = os.environ.get("NCL_FAKE_RESULT", "success")
GRID = "https://spms.ncl.edu.tw/NLT/co/media_discussion.jsp"
RELOADED = {"yes": False}
START = time.time()
MARK = {"on": False}
AGREED = {"yes": False}
# Scenario knobs (all absolute epoch seconds, chosen by the test):
#   NCL_FAKE_SESSION  JSON [[epoch, "valid"|"login"|"unknown"], ...]  session as the page shows it
#   NCL_FAKE_TERMS    hash of the rules dialog shown until accepted; NCL_FAKE_AGREE_AT = manual accept time
#   NCL_FAKE_GUARD    JSON {"periodic":..,"lead":..,"margin":..,"stop":..} to shorten the session guard
#   NCL_FAKE_FIELDS   "bad" makes the login-form structure check fail (wrong path)
#   NCL_FAKE_CREDS    "account:password" preloaded into a fake in-memory keyring


def session_now():
    plan = json.loads(os.environ.get("NCL_FAKE_SESSION", '[[0, "valid"]]'))
    state = "valid"
    for epoch, name in plan:
        if time.time() >= epoch:
            state = name
    return state


def probe_dict():
    state = session_now()
    base = {"host": "NCL", "path": "/NLT/co/multimedia.jsp", "logout": False, "records": False,
            "welcome": False, "agree_dialog": False, "date_grid": False,
            "login_marker": MARK["on"], "password_fields": 0}
    if state == "valid":
        base.update(logout=True, records=True, welcome=True)
    elif state == "login":
        base.update(password_fields=1)
    elif state == "offsite":
        return {"host": "OTHER"}
    return base


def log(kind, **fields):
    with open(EVENTS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"t": time.time(), "kind": kind, **fields}) + "\n")


class Element:
    def __init__(self, kind="submit"):
        self.kind = kind
        ids = {"account": ("name", "name"), "password": ("password", "psword"),
               "captcha": ("insrand", "insrand")}
        if kind in ids:
            self.attrs = {"id": ids[kind][0], "name": ids[kind][1]}

    async def clear_input(self):
        log("cleared", field=self.kind)

    async def send_keys(self, key):
        if self.kind == "submit":
            log("submit_keypress")
        else:
            log("typed", field=self.kind, length=len(str(key)))   # never the text itself


class Tab:
    async def evaluate(self, script):
        if script == "location.href":
            return GRID
        if "password_fields" in script and "logout" in script:
            log("probe", state=session_now())
            return probe_dict()
        if script.startswith("(() => { window.__nclLoginMarker"):
            MARK["on"] = True
            log("marker")
            return True
        if "same_form" in script:
            ok = os.environ.get("NCL_FAKE_FIELDS") != "bad"
            return {"host_ok": True, "path_ok": ok, "counts": {"account": 1, "password": 1, "captcha": 1},
                    "distinct": True, "same_form": True, "attrs_ok": True, "types_ok": True}
        if "cyrb53" in script:
            terms = os.environ.get("NCL_FAKE_TERMS")
            if terms and not AGREED["yes"]:
                return {"present": True, "hash": terms}
            return {"present": False, "hash": None}
        if "const action =" in script:
            log("entry", allow="const action = true;" in script)
            terms = os.environ.get("NCL_FAKE_TERMS")
            if terms and not AGREED["yes"]:
                if "const action = true;" in script:
                    AGREED["yes"] = True
                    log("agree_click")
                    return "GRID_READY"
                if time.time() >= float(os.environ.get("NCL_FAKE_AGREE_AT", "1e18")):
                    AGREED["yes"] = True
                    log("agree_manual")
                    return "GRID_READY"
                return "AGREEMENT_REQUIRED"
            # Simulates a lost login: after the first reload the site no longer shows the grid.
            return os.environ.get("NCL_FAKE_ENTRY_AFTER_RELOAD") or "GRID_READY" if RELOADED["yes"] \
                else "GRID_READY"
        if script.startswith('document.readyState === "complete"'):
            return True
        if "__nclSubmitProbe" in script:
            return "ARMED" if "addEventListener" in script else {"click": True, "trusted": True, "ajax": True}
        match = re.search(r'"phase": "(\w+)"', script)
        if match is None:
            return None
        phase = match.group(1)
        slot = re.search(r'"slot": "([^"]+)"', script).group(1)
        log("phase", phase=phase, slot=slot)
        if phase == "submit":
            return {"code": "READY_FOR_POINTER_CLICK", "x": 10.0, "y": 10.0}
        if phase == "success":
            return {"code": {"success": "SUCCESS_PAGE_MATCHED", "unverified": "SUCCESS_NOT_VERIFIED",
                             "failure": "FAILURE_SHOWN"}[RESULT]}
        return {"code": "CLICKED"}

    async def reload(self, **kwargs):
        log("reload")
        RELOADED["yes"] = True
        if os.environ.get("NCL_FAKE_RELOAD_ERROR"):
            raise OSError("network is down")

    async def wait_for_ready_state(self, **kwargs):
        return None

    async def select(self, selector, timeout=10):
        kind = {"input#name": "account", "input#password": "password", "input#insrand": "captcha"}.get(selector)
        if kind:
            return Element(kind)
        return Element()

    async def get(self, url):
        log("navigate")
        return self

    async def save_screenshot(self, path):
        Path(path).write_bytes(b"png")


class Browser:
    stopped = True  # "the user already closed Chrome": the engine exits at once

    async def get(self, url):
        log("open_site")
        return Tab()


async def start(**kwargs):
    log("browser_start", has_path="browser_executable_path" in kwargs)
    return Browser()


keys = types.SimpleNamespace(SpecialKeys=types.SimpleNamespace(SPACE="SPACE"))
sys.modules["zendriver"] = types.SimpleNamespace(start=start)
sys.modules["zendriver.core"] = types.SimpleNamespace(keys=keys)
sys.modules["zendriver.core.keys"] = keys

if os.environ.get("NCL_FAKE_CREDS"):
    import keyring
    from keyring.backend import KeyringBackend

    class MemoryKeyring(KeyringBackend):
        priority = 1
        store = {}

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def get_password(self, service, username):
            return self.store.get((service, username))

        def delete_password(self, service, username):
            self.store.pop((service, username), None)

    keyring.set_keyring(MemoryKeyring())
    account, password = os.environ["NCL_FAKE_CREDS"].split(":", 1)
    from ncl_openlab_credentials import CredentialStore
    CredentialStore().save(account, password)

import ncl_openlab_autobook as engine  # noqa: E402
import ncl_openlab_auth as auth  # noqa: E402

if os.environ.get("NCL_FAKE_GUARD"):
    knobs = json.loads(os.environ["NCL_FAKE_GUARD"])
    auth.PERIODIC, auth.CHECK_LEAD = knobs["periodic"], knobs["lead"]
    auth.RECOVER_MARGIN, auth.STOP_GUARD_AT = knobs["margin"], knobs["stop"]
    auth.REAL_CHECK_MIN_AGE = knobs.get("min_age", 0)
    engine.RECOVER_MARGIN = auth.RECOVER_MARGIN

if __name__ == "__main__":
    engine.main()
