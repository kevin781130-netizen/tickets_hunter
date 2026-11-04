"""Windows 11 / macOS compatibility checks that can run anywhere (no real OS required).

These prove the shared code has no single-OS gate and that each platform-specific
branch does the right thing under a simulated platform. They do NOT replace a run
on a real Mac or Windows machine (reported as NOT_RUN).
"""
import ast
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import ncl_openlab_control as ctl
import ncl_openlab_picker_model as model

NCL_SOURCES = sorted(SRC.glob("ncl_*.py"))


class LauncherTests(unittest.TestCase):
    def test_windows_cmd_launcher_is_kept(self):
        text = (ROOT / "launch_ncl_picker.cmd").read_text(encoding="utf-8")
        self.assertIn("pythonw.exe", text)
        self.assertIn(r"src\ncl_openlab_picker.py", text)
        self.assertIn("keyring==25.6.0", text)            # Credential Manager access

    def test_macos_command_launcher_exists_and_is_wired_to_the_same_gui(self):
        path = ROOT / "launch_ncl_picker.command"
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/bin/bash"))
        self.assertIn('cd "$(dirname "$0")"', text)
        self.assertIn("src/ncl_openlab_picker.py", text)
        self.assertIn("zendriver==0.16.0", text)          # same pin as requirement.txt
        self.assertIn("keyring==25.6.0", text)            # Keychain access for saved logins
        self.assertIn("import tkinter", text)             # explains a Tk-less Python
        requirement = (ROOT / "requirement.txt").read_text(encoding="utf-8")
        self.assertIn("zendriver==0.16.0", requirement)
        self.assertIn("keyring==25.6.0", requirement)
        self.assertNotIn("\r", text, "CRLF would break the shebang on macOS")

    @unittest.skipUnless(shutil.which("bash"), "NOT_RUN: bash unavailable")
    def test_macos_launcher_has_valid_shell_syntax(self):
        done = subprocess.run(["bash", "-n", str(ROOT / "launch_ncl_picker.command")],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    @unittest.skipUnless(shutil.which("git"), "NOT_RUN: git unavailable")
    def test_macos_launcher_is_committed_executable(self):
        listing = subprocess.run(["git", "ls-files", "-s", "launch_ncl_picker.command"],
                                 cwd=ROOT, capture_output=True, text=True).stdout
        self.assertTrue(listing.startswith("100755"), listing)

    def test_launcher_line_endings_are_pinned_in_gitattributes(self):
        attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8") if (ROOT / ".gitattributes").exists() else ""
        self.assertIn("*.command text eol=lf", attrs)


class NoSingleOsGateTests(unittest.TestCase):
    def test_gui_has_no_windows_only_gate_and_no_native_buttons(self):
        source = (SRC / "ncl_openlab_picker.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for needle in ('os.name == "nt"', "CREATE_NEW_CONSOLE", "僅支援 Windows"):
            self.assertNotIn(needle, source)
        calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        # macOS Tk ignores tk.Button colours (white-on-white); FlatButton/Label is used instead.
        self.assertNotIn("tk.Button", calls)
        for binding in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.assertIn(binding, source)

    def test_every_ncl_source_compiles_and_has_no_emoji(self):
        for path in NCL_SOURCES:
            text = path.read_text(encoding="utf-8")
            compile(text, str(path), "exec")
            self.assertFalse(any(0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF
                                 for c in text), path.name)

    def test_engine_and_interpreter_paths_are_platform_independent(self):
        for platform in ("win32", "darwin", "linux"):
            with patch.object(sys, "platform", platform):
                cmd = model.engine_command(["--date", "2026-11-12"], "/usr/bin/python3")
            self.assertEqual(Path(cmd[1]).name, "ncl_openlab_autobook.py")
            self.assertEqual(cmd[2:], ["--date", "2026-11-12"])
        self.assertEqual(model.console_python("/Users/k/.venv/bin/python3"), "/Users/k/.venv/bin/python3")
        self.assertEqual(model.console_python(r"C:\p\.venv\Scripts\pythonw.exe"),
                         r"C:\p\.venv\Scripts\python.exe")

    def test_engine_arguments_are_identical_on_every_platform(self):
        from datetime import date
        outputs = set()
        for platform in ("win32", "darwin", "linux"):
            with patch.object(sys, "platform", platform):
                outputs.add(tuple(model.build_booking_args(
                    day=date(2026, 11, 12), room="p03", slots=["13:00-14:00"], auto_submit=True,
                    run_at=model.parse_start_fields("2026-11-05", "00:00:00"), machine_status=True)))
        self.assertEqual(len(outputs), 1)


class SpawnPerPlatformTests(unittest.TestCase):
    def spawn(self, platform):
        popen = MagicMock()
        popen.return_value.stdout = iter(())
        sup = ctl.RunSupervisor(["py", "engine"], popen=popen, lock_path=ROOT / "nonexistent" / "x.lock",
                                alive=lambda pid: False)
        with patch.object(ctl.sys, "platform", platform), \
                patch.object(ctl.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            sup.start()
        return popen.call_args.kwargs

    def test_windows_hides_the_console_window(self):
        self.assertEqual(self.spawn("win32")["creationflags"], 0x08000000)

    def test_macos_and_linux_pass_no_windows_flags(self):
        for platform in ("darwin", "linux"):
            self.assertNotIn("creationflags", self.spawn(platform))

    def test_children_always_speak_utf8_over_piped_stdio(self):
        for platform in ("win32", "darwin"):
            kwargs = self.spawn(platform)
            self.assertEqual((kwargs["encoding"], kwargs["env"]["PYTHONUTF8"],
                              kwargs["env"]["PYTHONUNBUFFERED"]), ("utf-8", "1", "1"))
            self.assertTrue(kwargs["text"])


class PidAliveTests(unittest.TestCase):
    def test_windows_branch_never_signals_the_process(self):
        kernel = MagicMock()
        kernel.OpenProcess.return_value = 7
        kernel.GetExitCodeProcess.side_effect = lambda handle, ref: (setattr(ref._obj, "value", 259) or 1)
        fake_ctypes = MagicMock()
        fake_ctypes.windll.kernel32 = kernel
        import ctypes
        fake_ctypes.c_ulong = ctypes.c_ulong
        fake_ctypes.byref = ctypes.byref
        with patch.dict(sys.modules, {"ctypes": fake_ctypes}), \
                patch.object(ctl.os, "kill", side_effect=AssertionError("os.kill terminates on Windows")):
            self.assertTrue(ctl.pid_alive(1234, platform="win32"))
            kernel.OpenProcess.return_value = 0
            self.assertFalse(ctl.pid_alive(1234, platform="win32"))
        kernel.CloseHandle.assert_called()


if __name__ == "__main__":
    unittest.main()
