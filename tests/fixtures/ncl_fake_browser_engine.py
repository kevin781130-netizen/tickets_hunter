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


def log(kind, **fields):
    with open(EVENTS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"t": time.time(), "kind": kind, **fields}) + "\n")


class Element:
    async def send_keys(self, key):
        log("submit_keypress")


class Tab:
    async def evaluate(self, script):
        if script == "location.href":
            return GRID
        if "const action =" in script:
            log("entry")
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

import ncl_openlab_autobook as engine  # noqa: E402

if __name__ == "__main__":
    engine.main()
