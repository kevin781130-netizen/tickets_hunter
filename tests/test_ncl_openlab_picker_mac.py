"""Offline end-to-end wiring test: picker click -> argv -> macOS Terminal.

No Tk window is created; no real Terminal, Chrome, or reservation runs.
"""
import importlib.util
import json
import shlex
import subprocess
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from ncl_openlab_launcher import (
    launch_booking_command, mac_terminal_script,
)


class MacLauncherTests(unittest.TestCase):
    def test_macos_terminal_quotes_paths_and_keeps_results_visible(self):
        cwd = "/Users/ilka/Booking's Project"
        cmd = ["/Users/ilka/ncl-openlab/.venv/bin/python",
               "/Users/ilka/ncl-openlab/src/ncl_openlab_autobook.py",
               "--date", "2026-11-11", "--slots",
               "13:00-16:00,17:00-20:00", "--auto-submit"]
        script = mac_terminal_script(cmd, cwd)
        line = next(line for line in script.splitlines()
                    if "do script " in line).split("do script ", 1)[1]
        shell = json.loads(line)
        self.assertTrue(
            shell.startswith("cd " + shlex.quote(cwd) +
                             " && " + shlex.join(cmd)))
        self.assertIn("NCL_PROCESS_EXIT=%s", shell)
        self.assertIn("read -r _", shell)
        self.assertIn('tell application "Terminal"', script)

    def test_macos_invokes_terminal_without_sending_booking_request(self):
        with patch("ncl_openlab_launcher.subprocess.run") as launch:
            launch_booking_command(["/tmp/.venv/bin/python", "bot.py",
                                    "--auto-submit"], "/tmp", platform="darwin")
        launch.assert_called_once()
        args, kwargs = launch.call_args
        self.assertEqual(args[0][:2], ["osascript", "-e"])
        self.assertEqual(kwargs["cwd"], "/tmp")
        self.assertTrue(kwargs["check"])
        self.assertTrue(kwargs["capture_output"])
        self.assertNotIn("browser", str(launch.call_args))

    def test_windows_uses_original_console_behavior(self):
        # CREATE_NEW_CONSOLE exists on Windows, not on the Mac test host.
        with (patch.object(subprocess, "CREATE_NEW_CONSOLE", 16, create=True),
              patch("ncl_openlab_launcher.subprocess.Popen") as launch):
            launch_booking_command(["python.exe", "bot.py"], "C:\\tmp",
                                   platform="win32")
        launch.assert_called_once_with(
            ["python.exe", "bot.py"], cwd="C:\\tmp",
            creationflags=16)

    def test_unsupported_platform_is_fail_closed(self):
        with (patch("ncl_openlab_launcher.subprocess.Popen") as popen,
              patch("ncl_openlab_launcher.subprocess.run") as run):
            with self.assertRaises(OSError):
                launch_booking_command(["python", "bot.py"], "/tmp",
                                       platform="linux")
        popen.assert_not_called()
        run.assert_not_called()

    def test_terminal_error_is_not_reported_as_success(self):
        err = subprocess.CalledProcessError(
            1, ["osascript"], stderr="Not authorized to control Terminal")
        with patch("ncl_openlab_launcher.subprocess.run", side_effect=err):
            with self.assertRaisesRegex(OSError, "Not authorized"):
                launch_booking_command(["python", "bot.py"], "/tmp",
                                       platform="darwin")


class GuiToBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The GUI class is imported against a Tk stub; no display is needed.
        fake_tk = types.ModuleType("tkinter")
        fake_tk.Tk = object
        fake_tk.messagebox = types.SimpleNamespace(
            askyesno=MagicMock(return_value=True),
            showwarning=MagicMock(), showerror=MagicMock(),
            showinfo=MagicMock())
        fake_tk.ttk = types.SimpleNamespace()
        spec = importlib.util.spec_from_file_location(
            "ncl_picker_ui_test", SRC / "ncl_openlab_picker.py")
        mod = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"tkinter": fake_tk}):
            spec.loader.exec_module(mod)
        cls.ui = mod

    def picker(self, slots, *, authorized=True):
        return types.SimpleNamespace(
            selected_date=date(2026, 11, 11),
            room=types.SimpleNamespace(get=lambda: "music"),
            slots=slots,
            immediate=types.SimpleNamespace(get=lambda: True),
            authorize_submit=types.SimpleNamespace(get=lambda: authorized),
            accept_terms=types.SimpleNamespace(get=lambda: True),
        )

    def test_gui_button_launches_real_backend_entry_with_two_slots(self):
        with patch.object(self.ui, "launch_booking_command") as start:
            self.ui.BookingPicker._launch(
                self.picker(["13:00-16:00", "17:00-20:00"]))
        start.assert_called_once()
        cmd, cwd = start.call_args.args
        self.assertTrue(str(cmd[1]).endswith("ncl_openlab_autobook.py"))
        self.assertEqual(cmd[cmd.index("--date") + 1], "2026-11-11")
        self.assertEqual(cmd[cmd.index("--room") + 1], "music")
        self.assertEqual(cmd[cmd.index("--slots") + 1],
                         "13:00-16:00,17:00-20:00")
        self.assertIn("--reserve-two", cmd)
        self.assertIn("--auto-submit", cmd)
        self.assertIn("--accept-terms", cmd)
        self.assertIn("--now", cmd)
        self.assertEqual(Path(cwd), SRC.parent)

    def test_gui_button_refuses_start_without_submit_consent(self):
        with patch.object(self.ui, "launch_booking_command") as start:
            self.ui.BookingPicker._launch(
                self.picker(["13:00-16:00"], authorized=False))
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
