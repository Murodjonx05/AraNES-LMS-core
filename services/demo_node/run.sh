#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SERVICE_PORT:-}" ]]; then
  echo "SERVICE_PORT is required" >&2
  exit 1
fi

exec node server.js
