"""Protocol stub for GUI/supervisor tests: speaks @@NCL lines, never opens a browser.

Argv is parsed by the REAL engine parser, so anything the GUI passes that the
engine would reject fails here. Scenario comes from NCL_STUB_MODE.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import ncl_openlab_autobook as engine  # noqa: E402
from ncl_openlab_control import encode_event  # noqa: E402
from ncl_openlab_schedule import parse_run_at  # noqa: E402


def say(state, **fields):
    print(encode_event(state, **fields), flush=True)


def main():
    args = engine.build_parser().parse_args(sys.argv[1:])
    mode = os.environ.get("NCL_STUB_MODE", "success")
    keys = ("room", "date", "slots", "run_at", "auto_submit", "now", "reserve_two",
            "sync_clock", "machine_status")
    print("ARGS " + json.dumps({k: str(getattr(args, k)) for k in keys}, ensure_ascii=False),
          flush=True)
    say("LAUNCHING")
    auth = os.environ.get("NCL_STUB_AUTH")
    if auth:      # auth-check engines do not wait for a keyboard Enter
        say("LOGIN", auth=auth, detail="")
        if auth == "AUTH_INTERACTION_REQUIRED":
            sys.stdin.readline()          # the manual-confirmation fallback
        else:
            time.sleep(float(os.environ.get("NCL_STUB_AUTH_WAIT", "0.6")))
        say("LOGIN", auth="LOGIN_SUCCESS", detail="")
    else:
        say("LOGIN")
        first = sys.stdin.readline().strip().upper()
        if first == "CANCEL":
            say("DONE", outcome="CANCELLED_BEFORE_START")
            return
    cancelled = threading.Event()

    def watch():
        for line in sys.stdin:
            if line.strip().upper() == "CANCEL":
                cancelled.set()
                return
    threading.Thread(target=watch, daemon=True).start()
    run_at = parse_run_at(args.run_at) if args.run_at else None
    say("STANDBY", run_at=(run_at.isoformat() if run_at else "2026-11-05T00:00:00+08:00"),
        clock_offset=0.0)
    if mode == "garbage":
        print("@@NCL not-json", flush=True)
        print('@@NCL {"state": "BOGUS"}', flush=True)
        print("@@NCL " + json.dumps({"state": "STANDBY", "run_at": "x" * 500}), flush=True)
    wait_until = time.time() + float(os.environ.get("NCL_STUB_WAIT", "1.5"))
    while time.time() < wait_until:
        if cancelled.is_set():
            say("DONE", outcome="CANCELLED_BEFORE_START")
            return
        time.sleep(0.05)
    say("RUNNING")
    if mode == "crash_running":
        os._exit(3)
    outcome = {"success": "SUCCESS_PAGE_MATCHED", "unknown": "SUBMITTED_SUCCESS_UNVERIFIED",
               "fail": "RELEASE_REFRESH_BLOCKED_ENTRY_NOT_FOUND_OR_AMBIGUOUS",
               "garbage": "SUCCESS_PAGE_MATCHED", "two": "TWO_BOOKINGS_CONFIRMED",
               "partial": "SECOND_NOT_CONFIRMED_FAILURE_SHOWN"}[mode]
    say("DONE", outcome=outcome)


if __name__ == "__main__":
    main()
