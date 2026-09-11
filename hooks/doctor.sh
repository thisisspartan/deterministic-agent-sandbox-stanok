#!/usr/bin/env bash
# doctor.sh — structural invariants of the claude machine (grok doctor analog).
# Called by the operator before a run (see README Setup).
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
chk "commit-msg executable"           test -x "$REPO_ROOT/hooks/commit-msg"
HOOKS_DIR="$(git -C "$REPO_ROOT" rev-parse --git-path hooks 2>/dev/null || echo .git/hooks)"
chk "commit-msg hook"                 test -L "$REPO_ROOT/$HOOKS_DIR/commit-msg"   # FINDING-5: a broken symlink disables the TASK-ID gate
chk "CLAUDE.md exists"                test -f "$REPO_ROOT/CLAUDE.md"
chk "write-path src/tests/docs"       test -d "$REPO_ROOT/src" -a -d "$REPO_ROOT/tests" -a -d "$REPO_ROOT/docs"
chk "git repo initialized"            test -d "$REPO_ROOT/.git"

# --- Runner invariants (launcher/stanok.py; regression protection, feedback from "the elder brothers") ---
# All checks run with STANOK_PY=system python3: the SDK is imported
# lazily, the gates are pure stdlib, so the invariants work even without a deployed .venv.
# STANOK_NO_SANDBOX=1: the tests check the RUNNER, not the sandbox; bwrap mounts
# a private /tmp (--tmpfs /tmp), so mktemp /tmp/... tickets are invisible inside (rc=13).
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
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 STANOK_NO_SANDBOX=1 \
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
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 STANOK_NO_SANDBOX=1 \
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
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 STANOK_NO_SANDBOX=1 \
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

# 2c) preflight window (fail-closed): a LIVE server whose n_ctx is below the required
#     window (CLAUDE_CODE_AUTO_COMPACT_WINDOW from .claude/settings.stanok.json) -> rc=20.
MOCKPORT=59998
MOCKDIR="$(mktemp -d /tmp/doctor-mock-XXXXXX)"
cat > "$MOCKDIR/server.py" <<'PYEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"default_generation_settings": {"n_ctx": 4096}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PYEOF
python3 "$MOCKDIR/server.py" "$MOCKPORT" & MOCKPID=$!
sleep 1
TMPT4="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nplaceholder\n' > "$TMPT4"
DR2="doctor-window-$$-${RANDOM}"
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL="http://127.0.0.1:$MOCKPORT" STANOK_NO_SANDBOX=1 \
     "$LAUNCH" run "$TMPT4" "$DR2" >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner preflight-window: n_ctx below the required window must give rc=20"
else
  RC=$?
  case "$RC" in
    20) OK=$((OK+1)); echo "ok   runner preflight-window (small n_ctx -> rc=20)";;
    21) echo "skip runner preflight-window (a machine run is in progress — lock is held)";;
    22) echo "skip runner preflight-window (dirty tree — dirty-tree rc=22 before pre-flight)";;
    *)  FAIL=$((FAIL+1)); echo "FAIL runner preflight-window: expected rc=20, got rc=$RC";;
  esac
fi
kill "$MOCKPID" 2>/dev/null || true
rm -rf "$MOCKDIR" "$REPO_ROOT/evidence/$DR2" "/tmp/stanok-logs/$DR2" "$TMPT4"

# 3) ROLE-LEAK: a CLAUDE.md above the repo -> rc=24 (fail-closed, no side effects)
TMPROOT="$(mktemp -d /tmp/doctor-roleleak-XXXXXX)"
mkdir -p "$TMPROOT/repo"
touch "$TMPROOT/CLAUDE.md"                       # a "parent" CLAUDE.md = role leak
TMPT2="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nplaceholder\n' > "$TMPT2"
if STANOK_PY="$(command -v python3)" STANOK_REPO="$TMPROOT/repo" \
     STANOK_SERVER_URL=http://127.0.0.1:59999 STANOK_NO_SANDBOX=1 \
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
