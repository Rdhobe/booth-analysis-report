#!/usr/bin/env bash
# Starts the UPBI website (Next.js) on http://localhost:${PORT:-3000}. First run installs packages and builds (about 2 minutes).
# Not tested on macOS/Linux by the authors (tested on Windows 11); the commands are standard.
set -euo pipefail
cd "$(dirname "$0")/web"
PORT="${PORT:-3000}"; API_PORT="${API_PORT:-8000}"
command -v node >/dev/null || { echo "Node.js 20+ not found. Install the LTS version from https://nodejs.org/"; exit 1; }
[ -d node_modules ] || npm ci --no-audit --no-fund
[ -d .next ] || npm run build
export UPBI_API_BASE="http://127.0.0.1:${API_PORT}" NEXT_TELEMETRY_DISABLED=1
echo "Website starting. Open: http://localhost:${PORT}   (the API must be running on port ${API_PORT}; Ctrl+C to stop)"
exec npx next start -H 127.0.0.1 -p "${PORT}"
