#!/bin/bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Install Python 3 first (sudo apt install python3 python3-venv)"; exit 1; }
if [ ! -x .venv/bin/python ]; then
  echo "First run: installing (only once)..."
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt playwright || exit 1
fi
while true; do
  .venv/bin/python -m tpclone run --open
  echo "The app stopped. Restarting in 10 seconds (Ctrl+C to quit)..."; sleep 10
done
