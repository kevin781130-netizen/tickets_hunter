@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "src\ncl_openlab_picker.py"
    exit /b 0
)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "src\ncl_openlab_picker.py"
    exit /b %errorlevel%
)
echo Could not find .venv\Scripts\python.exe. Install the Python environment first.
pause
exit /b 1
