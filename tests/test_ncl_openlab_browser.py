"""Chrome discovery on Windows/macOS/Linux, pipe draining, and deterministic clean-up."""
import asyncio
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import ncl_openlab_browser as nb


class FindChromeTests(unittest.TestCase):
    def test_macos_paths_include_user_applications(self):
        paths = nb.candidate_paths("darwin", {}, "/Users/kev")
        self.assertEqual(paths[0], "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        self.assertIn("/Users/kev/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", paths)

    def test_windows_paths_cover_all_standard_install_roots(self):
        env = {"PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
               "LOCALAPPDATA": r"C:\Users\k\AppData\Local"}
        joined = [p.replace("\\", "/") for p in nb.candidate_paths("win32", env, "C:/Users/k")]
        self.assertEqual(len(joined), 3)
        self.assertTrue(all(p.endswith("Google/Chrome/Application/chrome.exe") for p in joined))

    def test_linux_paths(self):
        self.assertIn("/usr/bin/google-chrome", nb.candidate_paths("linux", {}, "/home/k"))

    def test_first_existing_candidate_wins_per_platform(self):
        for platform, expected in (("darwin", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
                                   ("linux", "/usr/bin/chromium")):
            found = nb.find_chrome(platform, {}, "/h", is_file=lambda p, e=expected: p == e,
                                   which=lambda n: None)
            self.assertEqual(found, expected)

    def test_override_wins_and_a_missing_override_does_not_fall_back_silently(self):
        env = {nb.CHROME_ENV: "/custom/chrome"}
        self.assertEqual(nb.find_chrome("darwin", env, "/h", is_file=lambda p: True), "/custom/chrome")
        self.assertIsNone(nb.find_chrome("darwin", env, "/h", is_file=lambda p: p.startswith("/Applications")))

    def test_nothing_found_returns_none_without_crashing_on_a_missing_path_variable(self):
        self.assertIsNone(nb.find_chrome("darwin", {}, "/h", is_file=lambda p: False))
        self.assertIsNone(nb.find_chrome("win32", {}, "C:/h", is_file=lambda p: False))
        self.assertIsNone(nb.find_chrome("linux", {}, "/h", is_file=lambda p: False, which=lambda n: None))

    def test_posix_falls_back_to_path_lookup(self):
        found = nb.find_chrome("linux", {}, "/h", is_file=lambda p: False,
                               which=lambda n: "/opt/bin/chromium" if n == "chromium" else None)
        self.assertEqual(found, "/opt/bin/chromium")


class StartBrowserTests(unittest.TestCase):
    def test_start_passes_the_detected_executable_and_visible_mode(self):
        seen = {}

        class Uc:
            @staticmethod
            async def start(**kwargs):
                seen.update(kwargs)
                return type("B", (), {})()
        with patch.object(nb, "find_chrome", return_value="/found/chrome"):
            asyncio.run(nb.start_browser(Uc))
        self.assertEqual(seen, {"browser_executable_path": "/found/chrome", "headless": False})

    def test_unset_detection_lets_zendriver_search_but_a_bad_override_is_an_error(self):
        class Uc:
            @staticmethod
            async def start(**kwargs):
                return type("B", (), {"kwargs": kwargs})()
        with patch.object(nb, "find_chrome", return_value=None), patch.dict("os.environ", {}, clear=False):
            browser = asyncio.run(nb.start_browser(Uc))
        self.assertNotIn("browser_executable_path", browser.kwargs)
        with patch.object(nb, "find_chrome", return_value=None), \
                patch.dict("os.environ", {nb.CHROME_ENV: "/nope"}):
            with self.assertRaises(RuntimeError):
                asyncio.run(nb.start_browser(Uc))


class PipeDrainTests(unittest.TestCase):
    def test_a_chatty_child_never_blocks_on_unread_pipes(self):
        """zendriver leaves Chrome's pipes unread; a full pipe would freeze the browser."""
        code = ("import sys; chunk='x'*1024; "
                "[sys.stderr.write(chunk) or sys.stdout.write(chunk) for _ in range(2048)]; "
                "sys.stdout.flush(); sys.stderr.flush(); print('FINISHED', file=open('%s','w'))")
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "done.txt"
            process = subprocess.Popen([sys.executable, "-c", code % marker.as_posix()],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            browser = type("B", (), {"_process": process})()
            self.assertEqual(nb.start_pipe_drain(browser), 2)
            try:
                self.assertEqual(process.wait(timeout=20), 0)  # would hang forever without draining
                self.assertTrue(marker.exists())
            finally:
                if process.poll() is None:
                    process.kill()

    def test_fake_browsers_without_pipes_are_tolerated(self):
        self.assertEqual(nb.start_pipe_drain(object()), 0)
        self.assertEqual(nb.start_pipe_drain(type("B", (), {"_process": None})()), 0)


class Process:
    def __init__(self, alive=True):
        self.alive, self.killed = alive, False

    def poll(self):
        return None if self.alive else 0

    def kill(self):
        self.killed, self.alive = True, False


class CleanupTests(unittest.TestCase):
    def browser(self, *, stopped=False, hang=False, fail=False, process=None, config=None):
        calls = []

        class B:
            def __init__(self):
                self.stopped, self._process, self.config = stopped, process, config

            async def stop(self):
                calls.append("stop")
                if hang:
                    await asyncio.sleep(60)
                if fail:
                    raise RuntimeError("boom")
                self.stopped = True
        b = B()
        b.calls = calls
        return b

    def test_alive_browser_is_stopped_after_the_user_closed_the_windows(self):
        b = self.browser()
        self.assertEqual(asyncio.run(nb.cleanup_browser(b)), "stopped")
        self.assertEqual(b.calls, ["stop"])

    def test_already_closed_browser_is_not_touched(self):
        b = self.browser(stopped=True)
        self.assertEqual(asyncio.run(nb.cleanup_browser(b)), "nothing_to_do")
        self.assertEqual(b.calls, [])

    def test_hung_stop_falls_back_to_kill_and_never_raises(self):
        process = Process()
        b = self.browser(hang=True, process=process)
        status = asyncio.run(nb.cleanup_browser(b, timeout=0.05))
        self.assertTrue(process.killed)
        self.assertIn("stop_failed_TimeoutError", status)
        self.assertIn("killed", status)

    def test_failing_stop_never_raises(self):
        self.assertIn("stop_failed_RuntimeError",
                      asyncio.run(nb.cleanup_browser(self.browser(fail=True))))

    def test_cleanup_is_idempotent(self):
        b = self.browser()
        asyncio.run(nb.cleanup_browser(b))
        self.assertEqual(asyncio.run(nb.cleanup_browser(b)), "nothing_to_do")

    def test_only_zendriver_temp_profiles_are_deleted(self):
        class Config:
            def __init__(self, path, custom):
                self.user_data_dir, self.uses_custom_data_dir = str(path), custom
        import tempfile as tf
        temp = Path(tf.mkdtemp(prefix="uc_"))
        (temp / "Default").mkdir()
        mine = Path(tf.mkdtemp(prefix="my_profile_"))
        nested = Path(tf.mkdtemp()) / "deep"
        nested.mkdir()
        try:
            asyncio.run(nb.cleanup_browser(self.browser(stopped=True, config=Config(temp, False))))
            self.assertFalse(temp.exists())
            asyncio.run(nb.cleanup_browser(self.browser(stopped=True, config=Config(mine, True))))
            self.assertTrue(mine.exists(), "user-supplied profile must never be deleted")
            asyncio.run(nb.cleanup_browser(self.browser(stopped=True, config=Config(nested, False))))
            self.assertTrue(nested.exists(), "only direct children of the temp dir qualify")
        finally:
            for path in (mine, nested, nested.parent):
                import shutil
                shutil.rmtree(path, ignore_errors=True)


class EngineLifecycleTests(unittest.TestCase):
    """autobook(): Chrome is stopped only after the user closed it (or on cancel)."""

    def run_engine(self, answer, outcome="SUCCESS_PAGE_MATCHED"):
        import types
        from datetime import date
        import ncl_openlab_autobook as app

        events = []

        class Page:
            type_ = "page"

        class Browser:
            stopped, _process, config = False, None, None

            def __init__(self):
                self.polls = 0

            async def get(self, url):
                return object()

            async def _get_targets(self):
                self.polls += 1
                events.append("poll")
                return [Page()] if self.polls <= 2 else []

            async def stop(self):
                events.append("stop")
                self.stopped = True

        browser = Browser()

        async def start(**kwargs):
            return browser

        async def ready(*a, **k):
            return "GRID_READY"

        async def prompt(fn, text):
            return answer

        async def book(*a, **k):
            return outcome

        async def nap(seconds):
            return None

        with patch.dict(sys.modules, {"zendriver": types.SimpleNamespace(start=start)}), \
                patch.object(app, "ensure_date_grid", ready), \
                patch.object(app, "book_one_target", book), \
                patch.object(app.asyncio, "to_thread", prompt), \
                patch.object(app.asyncio, "sleep", nap):
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                result = asyncio.run(app.autobook(date(2026, 11, 12), ("13:00-14:00",),
                                                  auto_submit=True, now_mode=True, mode="p03"))
        return result, events

    def test_chrome_is_stopped_only_after_every_window_was_closed(self):
        result, events = self.run_engine("")
        self.assertEqual(result, "SUCCESS_PAGE_MATCHED")
        self.assertEqual(events, ["poll"] * 5 + ["stop"])   # 2 polls with a page, 3 without, then stop

    def test_cancel_closes_the_browser_immediately_without_waiting_for_the_user(self):
        result, events = self.run_engine("CANCEL")
        self.assertEqual(result, "CANCELLED_BEFORE_START")
        self.assertEqual(events, ["stop"])


if __name__ == "__main__":
    unittest.main()
