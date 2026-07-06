#!/usr/bin/env sh
# POSIX wrapper for preflight.py — confirms python3 exists before delegating, since
# preflight is the tool that detects a broken/absent interpreter and must not assume one.
set -eu
if ! command -v python3 >/dev/null 2>&1; then
  echo "preflight: python3 not found on PATH — install python3 first" >&2
  exit 2
fi
exec python3 "$(dirname "$0")/preflight.py" "$@"
