#!/usr/bin/env bash
# doctor.sh — thin wrapper (R5): the 15 checks live in
# launcher/tests_harness/test_doctor.py (pytest). Exit 0 only if all pass.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$DIR")"
PY="${STANOK_PY:-$REPO/.venv/bin/python}"
cd "$REPO"
exec "$PY" -m pytest launcher/tests_harness/ -q
