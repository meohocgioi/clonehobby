#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "Python 3 is not installed. Opening the download page..."; open https://www.python.org/downloads/; read -p "Install it, then double-click this file again. Press Enter."; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First run: installing (1-3 minutes, only once)..."
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt playwright || { echo "Install failed"; read -p "Press Enter"; exit 1; }
fi
while true; do
  .venv/bin/python -m tpclone run --open
  echo "The app stopped. Restarting in 10 seconds (close this window to quit)..."; sleep 10
done
