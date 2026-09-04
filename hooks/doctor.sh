#!/usr/bin/env bash
# doctor.sh — structural invariants of the claude machine (grok doctor analog).
# Called from claude-stanok.sh BEFORE exec claude (P3: SessionStart exit!=0 does not abort -p).
# Prints "N ok, M fail"; exit 0 ONLY if all checks passed.
# REPO_ROOT is derived from the script location — the hook is portable.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
OK=0; FAIL=0

chk() { # chk <name> <cmd...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    OK=$((OK+1)); echo "ok   $name"
  else
    FAIL=$((FAIL+1)); echo "FAIL $name"
  fi
}

chk "settings.stanok.json exists"     test -f "$REPO_ROOT/.claude/settings.stanok.json"
chk "settings.stanok.json valid JSON" python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$REPO_ROOT/.claude/settings.stanok.json"
chk "PreToolUse hook present"         grep -q '"PreToolUse"' "$REPO_ROOT/.claude/settings.stanok.json"
chk "path-guard.sh executable"        test -x "$REPO_ROOT/hooks/path-guard.sh"
chk "commit-msg executable"           test -x "$REPO_ROOT/hooks/commit-msg"
chk "commit-msg .git symlink"         test -L "$REPO_ROOT/.git/hooks/commit-msg"   # FINDING-5: a broken symlink disables the TASK-ID gate
chk "CLAUDE.md exists"                test -f "$REPO_ROOT/CLAUDE.md"
chk "write-path src/tests/docs"       test -d "$REPO_ROOT/src" -a -d "$REPO_ROOT/tests" -a -d "$REPO_ROOT/docs"
chk "git repo initialized"            test -d "$REPO_ROOT/.git"

# --- PATCH 5: cloud silence invariant --------------------------------------------
# The only artifact of cloud_review() — cloud-review-*.jsonl in evidence. Without an explicit
# --cloud (DOCTOR_EXPECT_NO_CLOUD=1, set by the launcher), no such files
# should exist within the WINDOW_H window. A false cloud call (creds/config leak) => FAIL => the run is aborted.
EVIDENCE="${STANOK_EVIDENCE:-$REPO_ROOT/evidence}"
WINDOW_H="${DOCTOR_CLOUD_WINDOW_H:-24}"

if [ "${DOCTOR_EXPECT_NO_CLOUD:-0}" = "1" ]; then
  CLOUD_ARTIFACTS="$(find "$EVIDENCE" -maxdepth 1 -name 'cloud-review-*.jsonl' \
    -mmin "-$((WINDOW_H*60))" 2>/dev/null | sort)"
  if [ -z "$CLOUD_ARTIFACTS" ]; then
    OK=$((OK+1)); echo "ok   cloud-silence (no cloud-review-*.jsonl in the last ${WINDOW_H}h)"
  else
    FAIL=$((FAIL+1)); echo "FAIL cloud-silence: cloud-review-*.jsonl found with DOCTOR_EXPECT_NO_CLOUD=1:"
    printf '%s\n' "$CLOUD_ARTIFACTS" | sed 's/^/     /'
  fi
else
  echo "skip cloud-silence (DOCTOR_EXPECT_NO_CLOUD unset — cloud is legitimately allowed)"
fi

# --- Runner invariants (launcher/stanok.py; regression protection, feedback from "the elder brothers") ---
# All checks run with STANOK_PY=system python3: SDK/telegram are imported
# lazily, the gates are pure stdlib, so the invariants work even without a deployed .venv.
# 1) label-guard: a label starting with '--' -> rc=15 BEFORE flags/ROLE-LEAK/lock
#    (protection against evidence/--background when the label is forgotten). argparse swallows '--background'
#    as a flag itself (rc=2), so we check the reachable path: an explicit '--'.
# 2) fail-fast: a dead server -> rc=20 along the ticket->dirty-tree->lock->pre-flight path.
#    On a dirty tree, dirty-tree (rc=22) fires BEFORE pre-flight — this is a valid
#    refusal (skip), not a test regression.
# 2b) dirty-tree: an uncommitted file -> rc=22 (reset --hard + clean -fdq would erase
#    the operator's work; the machine refuses to start, the TUI commits first).
# 3) ROLE-LEAK: a parent CLAUDE.md above the repo -> rc=24 BEFORE lock/mkdir (fail-closed,
#    equivalent to the old rc=25: the Runner is Python itself, "python3 disappeared" is no longer possible).
LAUNCH="$REPO_ROOT/launch.sh"

# 1) label-guard (rc=15): a label starting with '--' -> rc=15 BEFORE ticket resolution.
# The ticket EXISTS (mktemp), so that rc=13 is not masked when the label-guard is absent.
TMPT_LG="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nplaceholder\n' > "$TMPT_LG"
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 \
     "$LAUNCH" run "$TMPT_LG" -- --background >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner label-guard: label '--background' must give rc=15"
else
  RC=$?
  case "$RC" in
    15) OK=$((OK+1)); echo "ok   runner label-guard ('--background' -> rc=15)";;
    *)  FAIL=$((FAIL+1)); echo "FAIL runner label-guard: expected rc=15, got rc=$RC";;
  esac
fi
rm -f "$TMPT_LG"

# 2) fail-fast on a dead server (rc=20)
TMPT="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nplaceholder\n' > "$TMPT"
DR="doctor-dead-$$-${RANDOM}"
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 \
     "$LAUNCH" run "$TMPT" "$DR" >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner fail-fast: a dead server must give rc=20, but the run passed"
else
  RC=$?
  case "$RC" in
    20) OK=$((OK+1)); echo "ok   runner fail-fast (dead server -> rc=20)";;
    21) echo "skip runner fail-fast (a machine run is in progress — lock is held)";;
    22) echo "skip runner fail-fast (dirty tree — dirty-tree rc=22 before pre-flight)";;
    *)  FAIL=$((FAIL+1)); echo "FAIL runner fail-fast: expected rc=20, got rc=$RC";;
  esac
fi
rm -rf "$REPO_ROOT/evidence/$DR" "/tmp/stanok-logs/$DR" "$TMPT"

# 2b) dirty-tree: an uncommitted file in the repo -> rc=22 (fail-closed before pre-flight)
DIRTY="$REPO_ROOT/.doctor-dirty-marker"
printf 'marker\n' > "$DIRTY"
TMPT3="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nplaceholder\n' > "$TMPT3"
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 \
     "$LAUNCH" run "$TMPT3" doctor-dirty-$$ >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner dirty-tree: a dirty tree must give rc=22, but the run passed"
else
  RC=$?
  if [ "$RC" -eq 22 ]; then
    OK=$((OK+1)); echo "ok   runner dirty-tree (uncommitted file -> rc=22)"
  else
    FAIL=$((FAIL+1)); echo "FAIL runner dirty-tree: expected rc=22, got rc=$RC"
  fi
fi
rm -rf "$DIRTY" "$REPO_ROOT/evidence/doctor-dirty-$$" "/tmp/stanok-logs/doctor-dirty-$$" "$TMPT3"

# 3) ROLE-LEAK: a CLAUDE.md above the repo -> rc=24 (fail-closed, no side effects)
TMPROOT="$(mktemp -d /tmp/doctor-roleleak-XXXXXX)"
mkdir -p "$TMPROOT/repo"
touch "$TMPROOT/CLAUDE.md"                       # a "parent" CLAUDE.md = role leak
TMPT2="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nplaceholder\n' > "$TMPT2"
if STANOK_PY="$(command -v python3)" STANOK_REPO="$TMPROOT/repo" \
     "$LAUNCH" run "$TMPT2" doctor-roleleak-$$ >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner role-leak: a parent CLAUDE.md must give rc=24, but the run passed"
else
  RC=$?
  if [ "$RC" -eq 24 ]; then
    OK=$((OK+1)); echo "ok   runner role-leak (parent CLAUDE.md -> rc=24, before side effects)"
  else
    FAIL=$((FAIL+1)); echo "FAIL runner role-leak: expected rc=24, got rc=$RC"
  fi
fi
rm -rf "$TMPROOT" "$TMPT2"

echo "--- doctor: $OK ok, $FAIL fail ---"
[ "$FAIL" -eq 0 ]
