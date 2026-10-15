@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\serve.py --port 8000
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python scripts\serve.py --port 8000
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\serve.py --port 8000
  goto finished
)
echo Python 3.12+ is required. See README.md for setup instructions.
:finished
if errorlevel 1 echo Startup failed. See README.md for dependencies or port conflicts.
pause
