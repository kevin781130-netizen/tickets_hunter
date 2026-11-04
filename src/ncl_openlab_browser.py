# -*- coding: utf-8 -*-
"""Cross-platform Chrome discovery, start-up and clean-up for the NCL tools.

Why this exists (found by reading zendriver 0.16.0):
- It starts Chrome with stdout/stderr as PIPEs and never reads them again, so a
  long standby can fill the pipe and stall Chrome. We drain them in daemon threads.
- Its own Chrome lookup indexes os.environ["PATH"] and misses user-level installs.
- On macOS closing the last window leaves the Chrome process alive, so the
  temporary profile and the process outlive the tool. We stop both after the user
  has closed the windows (never while a result is on screen).
"""
import asyncio
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

CHROME_ENV = "NCL_CHROME_PATH"
STOP_TIMEOUT = 8.0


def candidate_paths(platform=None, env=None, home=None):
    """Likely Chrome/Chromium executables for the platform, best first."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    if platform == "darwin":
        apps = ("Google Chrome.app/Contents/MacOS/Google Chrome",
                "Chromium.app/Contents/MacOS/Chromium")
        return [str(root / app) for app in apps
                for root in (Path("/Applications"), home / "Applications")]
    if platform.startswith("win"):
        rel = ("Google", "Chrome", "Application", "chrome.exe")
        found = []
        for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "LOCALAPPDATA"):
            if env.get(key):
                found.append(str(Path(env[key], *rel)))
        return found
    return ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/opt/google/chrome/chrome",
            "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium"]


def find_chrome(platform=None, env=None, home=None, *, is_file=os.path.isfile, which=shutil.which):
    """Absolute path to a Chrome executable, or None to let zendriver try."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    override = env.get(CHROME_ENV)
    if override:
        return override if is_file(override) else None
    for path in candidate_paths(platform, env, home):
        if is_file(path):
            return path
    if platform != "darwin" and not platform.startswith("win"):
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = which(name)
            if found:
                return found
    return None


def _drain(stream):
    read = getattr(stream, "read1", None) or (lambda n: stream.read(1))
    try:
        while read(65536):
            pass
    except (OSError, ValueError):
        pass  # the pipe closed with the process


def start_pipe_drain(browser):
    """Keep Chrome's stdout/stderr pipes empty so it can never block on them."""
    process = getattr(browser, "_process", None)
    started = 0
    for name in ("stdout", "stderr"):
        stream = getattr(process, name, None)
        if stream is not None and hasattr(stream, "read"):
            threading.Thread(target=_drain, args=(stream,), daemon=True).start()
            started += 1
    return started


async def start_browser(uc, **kwargs):
    """Start a visible Chrome with a discovered executable and drained pipes."""
    path = find_chrome()
    if path is None and os.environ.get(CHROME_ENV):
        # An explicit choice that cannot be honoured must not silently fall back.
        raise RuntimeError(f"{CHROME_ENV} 指向的檔案不存在")
    if path:
        kwargs.setdefault("browser_executable_path", path)
    kwargs.setdefault("headless", False)
    browser = await uc.start(**kwargs)
    start_pipe_drain(browser)
    return browser


def _is_zendriver_temp_profile(config):
    """Only ever delete the throwaway profile zendriver itself created."""
    if getattr(config, "uses_custom_data_dir", True):
        return None
    path = getattr(config, "user_data_dir", None)
    if not path:
        return None
    target = Path(path).resolve()
    return target if target.parent == Path(tempfile.gettempdir()).resolve() else None


async def cleanup_browser(browser, *, timeout=STOP_TIMEOUT):
    """Idempotent, never raises. Returns a short status for logs/tests.

    Call only after the user closed the windows (or on cancel); never while a
    booking result is still displayed.
    """
    steps = []
    process = getattr(browser, "_process", None)
    try:
        if not getattr(browser, "stopped", True):
            await asyncio.wait_for(browser.stop(), timeout)
            steps.append("stopped")
    except Exception as exc:
        steps.append("stop_failed_" + type(exc).__name__)
    try:
        if process is not None and process.poll() is None:
            process.kill()
            steps.append("killed")
    except Exception:
        pass
    try:
        profile = _is_zendriver_temp_profile(getattr(browser, "config", None))
        if profile is not None and profile.exists():
            shutil.rmtree(profile, ignore_errors=True)
            steps.append("profile_removed")
    except Exception:
        pass
    return ",".join(steps) or "nothing_to_do"
