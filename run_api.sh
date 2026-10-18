#!/usr/bin/env bash
# Starts the UPBI API (FastAPI) on http://127.0.0.1:${PORT:-8000}. First run creates a Python environment.
# Not tested on macOS/Linux by the authors (tested on Windows 11); the commands are standard.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
if [ ! -x .venv/bin/python ]; then
  command -v python3 >/dev/null || { echo "Python 3.10+ not found. Install it first."; exit 1; }
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r server/requirements.txt
cd server
echo "API starting. Check it at: http://127.0.0.1:${PORT}/api/insights/meta   (Ctrl+C to stop)"
exec ../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "${PORT}"
