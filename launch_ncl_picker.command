#!/bin/bash
# macOS launcher for the NCL OPEN LAB booking console (double-click in Finder).
# Same Python code as Windows (launch_ncl_picker.cmd). Needs Python 3.11+ with Tk
# and Google Chrome. Nothing is stored; you log in to the website yourself.
cd "$(dirname "$0")" || exit 1

if [ -x ".venv/bin/python3" ]; then
    PY=".venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    echo "First run: creating .venv and installing zendriver and keyring (pinned, same as requirement.txt)..."
    python3 -m venv .venv && .venv/bin/python3 -m pip install --quiet "zendriver==0.16.0" "keyring==25.6.0" || {
        echo "Could not create the Python environment."; read -r -p "Press Enter to close"; exit 1; }
    PY=".venv/bin/python3"
else
    echo "python3 not found. Install Python 3.11+ from https://www.python.org/downloads/macos/"
    read -r -p "Press Enter to close"; exit 1
fi

# keyring stores your library-card login in the macOS Keychain (optional feature)
"$PY" -c "import keyring" >/dev/null 2>&1 || "$PY" -m pip install --quiet "keyring==25.6.0" >/dev/null 2>&1

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "This Python has no Tk. Use the python.org installer, or: brew install python-tk"
    read -r -p "Press Enter to close"; exit 1
fi

exec "$PY" src/ncl_openlab_picker.py
