@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Setting up Focus Coach...
  python -m venv .venv
  if errorlevel 1 goto fail
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
if not exist data mkdir data
.venv\Scripts\pythonw.exe -m focus_coach
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo Focus Coach could not start. If a window did not open, run this file from a terminal to see the error.
pause
exit /b 1
