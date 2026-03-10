#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SERVICE_PORT:-}" ]]; then
  echo "SERVICE_PORT is required" >&2
  exit 1
fi

if [[ -z "${SKIP_PIP_INSTALL:-}" ]] && [[ -f requirements.txt ]] && grep -Eq '^[[:space:]]*[^#[:space:]]' requirements.txt; then
  "${SERVICE_PYTHON:-python}" -m pip install --no-cache-dir -r requirements.txt
fi

exec "${SERVICE_PYTHON:-python}" -m uvicorn main:app --host 127.0.0.1 --port "${SERVICE_PORT}"
