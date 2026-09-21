#!/usr/bin/env bash
# doctor.sh — thin wrapper (R5): the checks live in
# launcher/tests_harness/test_doctor.py (pytest). Exit 0 only if all pass.
# Count them (do not hardcode the number in prose):
#   uv run --directory <repo> pytest launcher/tests_harness --collect-only -q | tail -1
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$DIR")"
exec uv run --directory "$REPO" pytest launcher/tests_harness/ -q
