@echo off
setlocal
cd /d "%~dp0"
title Toy-People to Telegram  (keep this window open - minimise it)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo.
  echo  Python is not installed yet. I will open the download page.
  echo  1. Download and run the installer
  echo  2. IMPORTANT: tick the box "Add python.exe to PATH" on the first screen
  echo  3. Then double-click Start-Windows.bat again
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: installing ^(1-3 minutes, only once^)...
  %PY% -m venv .venv || ( echo Could not create the environment & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt playwright || ( echo Install failed - check your internet & pause & exit /b 1 )
)

:loop
".venv\Scripts\python.exe" -m tpclone run --open
echo.
echo The app stopped. Restarting in 10 seconds... (close this window to quit)
timeout /t 10 /nobreak >nul
goto loop
