#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SERVICE_PORT:-}" ]]; then
  echo "SERVICE_PORT is required" >&2
  exit 1
fi

exec "${SERVICE_PYTHON:-python}" app.py
