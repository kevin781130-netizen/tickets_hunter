"""Run page scripts in headless Chromium against synthetic fixtures (offline).

Skips cleanly (``available() is False``) when Node/Playwright is missing, so
those tests are reported as SKIPPED -> NOT_VERIFIED, never as passed.
"""
import functools
import json
import shutil
import subprocess
from pathlib import Path

HARNESS = Path(__file__).resolve().parent / "fixtures" / "ncl_browser_harness.js"
TIMEOUT = 180


@functools.lru_cache(maxsize=1)
def available():
    node = shutil.which("node")
    if not node:
        return False
    try:
        probe = subprocess.run(
            [node, "-e", "require('playwright').chromium.executablePath()"],
            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def run_cases(cases):
    """cases: [{id, html, steps:[{js}|{click_prev_xy}], url?}] -> {id: result}"""
    done = subprocess.run(
        [shutil.which("node"), str(HARNESS)],
        input=json.dumps({"cases": cases}, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=TIMEOUT)
    if done.returncode != 0:
        raise RuntimeError("browser harness failed: " + done.stderr.decode("utf-8", "replace")[:300])
    data = json.loads(done.stdout.decode("utf-8"))
    return {item["id"]: item for item in data["results"]}


def codes(result):
    """Reduce step results to comparable codes (dict -> its 'code')."""
    out = []
    for step in result["steps"]:
        if isinstance(step, dict):
            if "clicked" in step:
                out.append("CLICKED_PAGE" if step["clicked"] else "NO_CLICK")
            else:
                out.append(step.get("code", step))
        else:
            out.append(step)
    return out
