# -*- coding: utf-8 -*-
"""Open an interactive, independent booking terminal on Windows or macOS.

This module only launches the explicitly configured CLI. It never books,
logs in, handles credentials, or interprets a launch as reservation success.
"""
import json
import shlex
import subprocess
import sys


def mac_terminal_script(command, cwd):
    """Build a safely quoted Terminal.app command; preserve final output."""
    if (not command or any(not isinstance(arg, str) or not arg
                           for arg in command) or not str(cwd)):
        raise ValueError("invalid booking command or working directory")
    shell_line = (
        f"cd {shlex.quote(str(cwd))} && {shlex.join(command)}"
        "; __ncl_exit=$?; "
        "printf '\\nNCL_PROCESS_EXIT=%s\\n' \"$__ncl_exit\"; "
        "printf '請檢查上方結果，按 Enter 結束終端...'; "
        "read -r _"
    )
    return (
        'tell application "Terminal"\n'
        '  activate\n'
        f'  do script {json.dumps(shell_line, ensure_ascii=False)}\n'
        'end tell'
    )


def launch_booking_command(command, cwd, *, platform=None):
    """Launch only; a successful return does NOT mean a booking succeeded."""
    current = sys.platform if platform is None else platform
    if current == "win32":
        return subprocess.Popen(
            list(command), cwd=str(cwd),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    if current == "darwin":
        try:
            return subprocess.run(
                ["osascript", "-e", mac_terminal_script(command, cwd)],
                cwd=str(cwd), capture_output=True, text=True,
                timeout=60, check=True,
            )
        except (subprocess.CalledProcessError,
                subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            raise OSError(f"Mac 終端啟動失敗：{detail}") from exc
    raise OSError("目前僅支援 Windows 與 macOS 的獨立預約終端")
