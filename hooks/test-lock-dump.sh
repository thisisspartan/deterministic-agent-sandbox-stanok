#!/usr/bin/env bash
# test-lock-dump.sh — P2-probe hook: DUMP of the full PreToolUse input (no verdict).
# Runs on a copy ONLY to confirm the .agent_type values (main Write vs
# tester Write). Not part of the live circuit.
# REPO_ROOT is derived from the script location — the hook is portable.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DUMP_DIR="$REPO_ROOT/.stanok-logs/dump"
mkdir -p "$DUMP_DIR"
cat >> "$DUMP_DIR/ptu-inputs.jsonl"
exit 0
