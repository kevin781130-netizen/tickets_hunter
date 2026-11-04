# -*- coding: utf-8 -*-
"""GUI <-> engine control plane for the NCL booking tools (no Tk, no browser).

Engine side prints one JSON line per state change, prefixed with ``@@NCL ``.
GUI side (RunSupervisor) starts the engine as a child process, turns those
lines into a UI state machine, and can send READY / CANCEL on stdin.

Only the pre-booking phases can be cancelled. Once RUNNING starts, a booking
is never aborted or repeated from here: an unknown result stays UNKNOWN.
"""
import json
import os
import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from ncl_openlab_diag import explain_outcome
from ncl_openlab_schedule import TAIPEI_TZ, format_countdown

PREFIX = "@@NCL "
ENGINE_STATES = ("LAUNCHING", "LOGIN", "STANDBY", "RUNNING", "DONE")
ACTIVE_STATES = ("LAUNCHING", "LOGIN", "STANDBY", "RUNNING")
CANCELLABLE = ("LAUNCHING", "LOGIN", "STANDBY")
FINAL_STATES = ("SUCCESS", "FAILED", "UNKNOWN", "CANCELLED", "FINISHED", "ERROR")
STATE_LABELS = {
    "IDLE": "尚未啟動", "LAUNCHING": "啟動瀏覽器中", "LOGIN": "等待你登入國圖",
    "STANDBY": "待命中（倒數）", "RUNNING": "執行預約中", "SUCCESS": "預約成功（已核對）",
    "FAILED": "預約失敗／未送出", "UNKNOWN": "結果未知（請至官網核對，勿重送）",
    "CANCELLED": "已取消", "FINISHED": "流程結束（未預約）", "ERROR": "程序異常結束",
}
_CATEGORY_TO_STATE = {
    "SUCCESS_CONFIRMED": "SUCCESS", "UNKNOWN_DO_NOT_RETRY": "UNKNOWN",
    "STOPPED_BY_DESIGN": "FINISHED", "DRY_RUN": "FINISHED", "CANCELLED": "CANCELLED",
}
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "ncl_reports"
LOCK_PATH = REPORT_DIR / "ncl_run.lock"
HISTORY_PATH = REPORT_DIR / "ncl_run_history.jsonl"
MAX_FIELD = 200
MAX_LOG_LINE = 400


# ---------------------------------------------------------------- protocol
def encode_event(state, **fields):
    if state not in ENGINE_STATES:
        raise ValueError("unknown engine state")
    return PREFIX + json.dumps({"state": state, **fields}, ensure_ascii=False)


def parse_event(line):
    """Return the event dict or None. Untrusted text never raises.

    The marker may follow an unterminated prompt on the same line, so it is
    searched for rather than required at column 0.
    """
    if not isinstance(line, str) or PREFIX not in line:
        return None
    try:
        data = json.loads(line[line.index(PREFIX) + len(PREFIX):])
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("state") not in ENGINE_STATES:
        return None
    return {k: (v[:MAX_FIELD] if isinstance(v, str) else v) for k, v in data.items()
            if isinstance(v, (str, int, float, bool, type(None)))}


def ui_state_for_outcome(code):
    """Map a terminal engine outcome code to the user-facing final state."""
    return _CATEGORY_TO_STATE.get(explain_outcome(code)["category"], "FAILED")


# ----------------------------------------------------------------- run lock
def pid_alive(pid, platform=None):
    """True when a process exists. Never signals the process (os.kill is unsafe on Windows)."""
    platform = platform or sys.platform
    if not isinstance(pid, int) or pid <= 0:
        return False
    if platform.startswith("win"):
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunLockBusy(RuntimeError):
    def __init__(self, pid):
        super().__init__(f"另一個預約程序正在執行（PID {pid}）")
        self.pid = pid


class RunLock:
    """One booking process at a time, across GUIs and terminals."""

    def __init__(self, path=LOCK_PATH, pid=None, alive=pid_alive):
        self.path, self.pid, self.alive = Path(path), pid or os.getpid(), alive
        self.held = False

    def owner(self):
        try:
            pid = int(json.loads(self.path.read_text(encoding="utf-8"))["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return pid if self.alive(pid) else None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner = self.owner()
                if owner is not None:
                    raise RunLockBusy(owner) from None
                try:
                    self.path.unlink()  # stale lock from a crashed run
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"pid": self.pid}))
            self.held = True
            return self
        raise RunLockBusy(self.owner() or 0)

    def release(self):
        if self.held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.held = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


# ------------------------------------------------------------- engine side
class CancelWatcher:
    """Reads CANCEL from stdin after the login prompt (never before it)."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdin
        self.event = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def _run(self):
        try:
            for line in self.stream:
                if line.strip().upper() == "CANCEL":
                    self.event.set()
                    return
        except (OSError, ValueError):
            pass

    def is_set(self):
        return self.event.is_set()


# ---------------------------------------------------------------- history
def append_history(entry, path=HISTORY_PATH):
    clean = {k: v for k, v in entry.items() if isinstance(v, (str, int, float, bool, list, type(None)))}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(clean, ensure_ascii=False) + "\n")


def read_history(limit=20, path=HISTORY_PATH):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-limit:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(rows))


# ---------------------------------------------------------------- GUI side
class DuplicateStart(RuntimeError):
    pass


class RunSupervisor:
    """Owns at most one engine child process and its UI state."""

    def __init__(self, argv, *, meta=None, popen=subprocess.Popen, cwd=None,
                 history_path=HISTORY_PATH, lock_path=LOCK_PATH, alive=pid_alive,
                 now=lambda: datetime.now(TAIPEI_TZ)):
        self.argv, self.meta = list(argv), dict(meta or {})
        self._popen, self._cwd, self._now = popen, cwd, now
        self._history_path, self._lock = history_path, RunLock(lock_path, alive=alive)
        self.state, self.run_at, self.clock_offset = "IDLE", None, 0.0
        self.outcome, self.process = None, None
        self.log = []          # (timestamp text, message)
        self.cancel_requested = False
        self._lines = queue.Queue()
        self._finalized = False

    # -- queries
    @property
    def active(self):
        return self.state in ACTIVE_STATES

    def countdown(self):
        """Seconds to the start time while STANDBY, else None."""
        if self.state != "STANDBY" or self.run_at is None:
            return None
        # The engine's clock is local time + offset, so remaining = target - (now + offset).
        return (self.run_at - self._now()).total_seconds() - self.clock_offset

    def countdown_text(self):
        seconds = self.countdown()
        return None if seconds is None else format_countdown(seconds)

    def _say(self, text):
        self.log.append((self._now().strftime("%H:%M:%S"), text))

    # -- commands
    def start(self):
        if self.active:
            raise DuplicateStart("已有預約程序在執行，請先等待或取消")
        owner = self._lock.owner()
        if owner is not None:
            raise DuplicateStart(f"另一個預約程序正在執行（PID {owner}）")
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      text=True, encoding="utf-8", errors="replace", bufsize=1,
                      cwd=self._cwd, env=env)
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.process = self._popen(self.argv, **kwargs)
        self.state, self.outcome, self.cancel_requested = "LAUNCHING", None, False
        self._finalized, self.run_at = False, None
        self._lines = queue.Queue()
        threading.Thread(target=self._read, args=(self.process, self._lines), daemon=True).start()
        self._say("啟動預約程序")

    @staticmethod
    def _read(process, sink):
        try:
            for line in process.stdout:
                sink.put(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass
        sink.put(None)

    def _send(self, text):
        try:
            self.process.stdin.write(text + "\n")
            self.process.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def confirm_login(self):
        """The user says login is finished; the engine then goes on standby."""
        if self.state != "LOGIN":
            return False
        self._say("使用者確認已登入，進入待命")
        return self._send("READY")

    def cancel(self):
        if self.state not in CANCELLABLE:
            return False
        self.cancel_requested = True
        self._say("使用者要求取消排程")
        self._send("CANCEL")
        return True

    def force_stop(self):
        """Last resort when a cancelled engine does not exit by itself."""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    # -- engine output
    def pump(self):
        """Apply queued engine output. Call from the GUI thread. True if anything changed."""
        changed = False
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                return changed
            changed = True
            if line is None:
                self._on_exit()
            else:
                self._on_line(line)

    def _on_line(self, line):
        event = parse_event(line)
        lead = line[:line.index(PREFIX)].strip() if PREFIX in line else line.strip()
        if lead:
            self._say(lead[:MAX_LOG_LINE])
        if event is None:
            return
        state = event["state"]
        if state == "DONE":
            self.outcome = str(event.get("outcome", ""))
            self._finish(ui_state_for_outcome(self.outcome))
            return
        if self.state in FINAL_STATES:
            return
        self.state = state
        if state == "STANDBY":
            from ncl_openlab_schedule import parse_run_at
            try:
                self.run_at = parse_run_at(str(event.get("run_at", "")))
            except ValueError:
                self.run_at = None
            self.clock_offset = float(event.get("clock_offset", 0.0) or 0.0)
        self._say(STATE_LABELS[state])

    def _on_exit(self):
        code = self.process.wait() if self.process is not None else None
        for pipe in (getattr(self.process, "stdin", None), getattr(self.process, "stdout", None)):
            try:
                pipe.close()
            except (OSError, ValueError, AttributeError):
                pass
        if not self._finalized:
            if self.state == "RUNNING":
                self.outcome = self.outcome or "PROCESS_EXITED_DURING_BOOKING"
                self._finish("UNKNOWN")
            elif self.cancel_requested and self.state in CANCELLABLE:
                self._finish("CANCELLED")
            else:
                self.outcome = self.outcome or f"PROCESS_EXIT_{code}"
                self._finish("ERROR")

    def _finish(self, final_state):
        if self._finalized:
            return
        self._finalized, self.state = True, final_state
        self._say(STATE_LABELS[final_state] + (f"（{self.outcome}）" if self.outcome else ""))
        try:
            append_history({"finished_taipei": self._now().isoformat(timespec="seconds"),
                            "state": final_state, "outcome": self.outcome,
                            "run_at": self.run_at.isoformat() if self.run_at else self.meta.get("run_at"),
                            **{k: v for k, v in self.meta.items() if k != "run_at"}},
                           self._history_path)
        except OSError:
            self._say("執行紀錄寫入失敗")
