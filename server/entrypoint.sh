#!/bin/sh
# Fetch the prebuilt store once (persisted on /data), then serve.
# Required env: STORE_URL (GitHub Release asset URL of servedb.sqlite)
#   on first boot, or bake/mount a store at DB_PATH yourself.
set -e
DB_PATH="${DB_PATH:-/data/servedb.sqlite}"
if [ ! -s "$DB_PATH" ]; then
  if [ -z "$STORE_URL" ]; then
    echo "FATAL: no store at $DB_PATH and STORE_URL is unset." >&2
    echo "Build one locally (Scripts/build_servedb.py), attach it to a" >&2
    echo "GitHub Release, and set STORE_URL to the asset URL." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$DB_PATH")"
  echo "downloading store ..."
  curl -fL --retry 3 -o "$DB_PATH" "$STORE_URL"
  echo "store ready: $(du -h "$DB_PATH" | cut -f1)"
fi
exec uvicorn server.app:app --host 0.0.0.0 \
  --port "${PORT:-8000}" --app-dir /app
