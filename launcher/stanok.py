#!/usr/bin/env python3
"""Stanok — context-engineered Runner on a local model.

Full integration with the L1 Supervisor:
  1. Single Continuous Session (ClaudeSDKClient): retries inside ONE session (99% KV cache).
  2. Strict summary.json contract (probe_result, errors) for L1.
  3. Adaptive Contract Lock: adaptation for creating tests from scratch and a ban on weakening assertions.
  4. Cumulative Token & Cache Telemetry: exact session_hit_rate calculation.
  5. Shielded Turn Watchdog: the turn timeout (default 1800s) is a terminal DoS
     circuit breaker — asyncio.shield() keeps the turn task alive past wait_for,
     so client.interrupt() runs cleanly and summary.json is written with the
     TURN-TIMEOUT code (rc=1) without the process dying on CancelledError.
  6. Verifier-output compression: last-N raw tail, no pattern heuristics at
     all (REVIEW-KISS-CLI-FIRST §3.3; the last substring filter — CC-138).
  7. Process cleanup: guaranteed at the container boundary via `docker stop -t 5`
     (client processes spawned with start_new_session=True are outside the
     host process group — the Reaper's os.killpg(0) does not reach them).

PLAN-HYGIENE 2026-10-08 (step 5): this module is the HUB — circuit constants,
mutable run state, ExitCode, SessionPlan, logging and label_paths. The
functional submodules (gates, ticket, verify, session, summary, cli, opik)
import the hub and access shared/mutable/monkeypatched state as `stanok.X`;
the hub exposes their names lazily via PEP 562 __getattr__, so `import stanok`
stays the single entry point for tests and callers. Running this file directly
enters the CLI (cli.main()).
"""

import dataclasses
import importlib
import json
import os
import re
import shutil
from enum import IntEnum

import sandbox  # R2: the Docker boundary (former sandbox-run.sh)

# --- Circuit constants -------------------------------------------------------------
LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
# If STANOK_REPO is not set, we go up one level (stanok/launcher -> stanok)
DEFAULT_REPO = os.path.abspath(os.path.join(LAUNCHER_DIR, ".."))
REPO_ROOT = os.path.abspath(os.environ.get("STANOK_REPO", DEFAULT_REPO))
LOG_DIR = os.environ.get("STANOK_LOG_DIR", "/tmp/stanok-logs")
os.makedirs(LOG_DIR, exist_ok=True)

DEFAULT_MODEL = "qwen3.8-flash-next-iq3_xxs"
LOCAL_MODEL = os.environ.get("STANOK_MODEL", DEFAULT_MODEL)
SERVER_URL = os.environ.get("STANOK_SERVER_URL", "http://127.0.0.1:8080")
CLAUDE_BIN = os.environ.get("STANOK_CLAUDE_BIN", shutil.which("claude") or "claude")

MAX_TEST_LINES = 60
MAX_TEST_BYTES = 4096
DEFAULT_RETRIES = int(os.environ.get("STANOK_LOCAL_RETRIES", "2"))

API_TIMEOUT_S = max(1.0, float(os.environ.get("STANOK_API_TIMEOUT_S", "600")))
TURN_TIMEOUT_S = float(os.environ.get("STANOK_TURN_TIMEOUT_S", "1800"))
# CLI --max-turns ceiling: max model calls (agentic turns) per single query().
STANOK_MAX_AGENT_TURNS = int(os.environ.get("STANOK_MAX_AGENT_TURNS", "60"))

if TURN_TIMEOUT_S <= API_TIMEOUT_S:
    TURN_TIMEOUT_S = API_TIMEOUT_S + max(15.0, API_TIMEOUT_S * 0.2)

API_TIMEOUT_MS = str(int(API_TIMEOUT_S * 1000))
# Native Bash replaces the old MCP `run` tool (Docker refactor): the model
# runs `bash scripts/run.sh {list,test,smoke}` directly; the boundary is the
# container, not a per-command allowlist.
CURATED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]

_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
# The ONE kind list for a ticket header (CC-132). `scripts` is a ZONE, not a
# kind: a path under scripts/ is declared with impl:/test:/docs:/edit: like
# any other path. `scripts: x.sh` is therefore not a declaration — it ends
# the header (this is the fix for the old docstring that advertised it).
_FILE_LINE_RE = re.compile(r"^(impl|test|docs|edit):\s*([A-Za-z0-9_./-]+)\s*$")
_RESET_NONE_RE = re.compile(r"^reset:\s*none\s*$", re.IGNORECASE)

_stdout_log_f = None
_marker_path = None
_evidence_dir = None
_live_dir = None
_INTERRUPTED_RC = 0


class ExitCode(IntEnum):
    """Launch-level exit codes — the `rc` field of summary.json (strict contract).

    1  defect (exhausted retries / contract violation) / docker missing;
    13 ticket: not found, header parse error, create-edit conflict, protected edit;
    14 workspace prep error; 15 invalid label;
    16 ENV-FAIL: test runner unavailable in the image (image defect, not a red test);
    17 background child died before writing the .running marker;
    20 server unavailable / context window fail-closed;
    21 lock held by another run; 22 dirty machine tree;
    24 role leak (parent CLAUDE.md above the repo);
    26 hidden/TEMP files in src/tests/docs/scripts;
    27 test-config files under tests/ (verdict-subversion, CC-151);
    28 sandbox.filesystem deny entry invalid (CC-107/CC-157).
    """
    DEFECT = 1
    TICKET = 13
    WORKSPACE = 14
    BAD_LABEL = 15
    ENV_FAIL = 16
    CHILD_DIED = 17
    SERVER = 20
    LOCK = 21
    DIRTY_TREE = 22
    ROLE_LEAK = 24
    HIDDEN_FILES = 26
    TEST_CONFIG = 27
    SANDBOX_CONFIG = 28


# T1 (CC-120): the single source of file policy (invariant I1). The policy
# consumers (parse/quarantine/contract_lock/verify_gate) read from this object;
# no consumer keeps a free-floating policy list. git is always ro. Neither the
# container's rw MOUNTS nor the :ro protected set is a field: the mounts are
# derived from declared_paths by declared_carveout (T4/CC-135) and the :ro binds
# from the same manifest the post-turn diff hashes (host_ro_paths/T4b), so no
# list in the plan can drift from the ticket or go stale. (The T2 probe_specs
# placeholder was dropped when T2 was burned — CC-131; protected_paths was
# dropped with the PreToolUse hook it fed — T5/CC-137.)
@dataclasses.dataclass(frozen=True)
class SessionPlan:
    declared_paths:  tuple[str, ...]  # ticket header: impl:/test:/docs:/edit:
    # git_mode was dropped (PLAN-HYGIENE 2026-10-08): .git is always RO (I7)
    # enforced at the mount layer — a field no consumer read was dead weight.
    # CC-125: `edit:`-declared paths are MODIFIED IN PLACE, not created from
    # scratch — prepare_workspace must not quarantine them. They stay in
    # declared_paths (positive contract + contract_lock exemption).
    edit_paths:      tuple[str, ...] = ()


# ==================================================================================
# Logging and events
# ==================================================================================
def log(msg: str = "") -> None:
    print(msg, flush=True)
    if _stdout_log_f is not None:
        try:
            _stdout_log_f.write(msg + "\n")
            _stdout_log_f.flush()
        except (OSError, ValueError):
            pass


def _safe_json_default(obj):
    if dataclasses.is_dataclass(obj):
        return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


def _write_stream_msg(file_obj, turn: int, msg) -> None:
    try:
        raw = json.dumps(
            {"turn": turn, "type": type(msg).__name__, "data": msg},
            default=_safe_json_default,
            ensure_ascii=False
        )
        file_obj.write(raw + "\n")
        file_obj.flush()
    except Exception as e:
        try:
            file_obj.write(json.dumps({
                "turn": turn,
                "type": type(msg).__name__,
                "serialization_error": str(e)
            }) + "\n")
            file_obj.flush()
        except OSError:
            pass


def label_paths(label: str) -> tuple[str, str]:
    """(evidence_dir, live_dir) for a label.

    Host: evidence/<label> holds the verdict (summary.json) the supervisor
    reads, LOG_DIR/<label> the session jsonl + quarantine.

    Container (CC-134): evidence/ is read-only through the repo :ro mount, so
    BOTH paths resolve into the rw LOG_DIR/<label>; the host publishes the
    verdict back into evidence/<label> after the container exits
    (_publish_evidence). Routed here, so every writer — summary.json,
    launcher.stdout.log, the .running marker — follows automatically.
    """
    live = os.path.join(LOG_DIR, label)
    if os.environ.get("STANOK_IN_CONTAINER") == "1":
        return (live, live)
    return (os.path.join(REPO_ROOT, "evidence", label), live)


# --- Facade (PLAN-HYGIENE 2026-10-08 split) ----------------------------------------
# The functional code lives in the submodules below. `import stanok` stays the
# single entry point: a name not defined on the hub is looked up lazily in the
# submodules (PEP 562 __getattr__). setattr on the hub (tests_harness
# monkeypatching) shadows the facade for the patched name; monkeypatch.undo
# restores the lookup. The submodules import the hub, never the reverse — no
# import cycle: the facade is the only hub->submodule edge and it is lazy.
_SUBMODULES = ("gates", "ticket", "verify", "session", "summary", "cli", "opik")


def __getattr__(name: str):
    for mod in _SUBMODULES:
        try:
            m = importlib.import_module(mod)
        except ImportError:
            continue
        try:
            return getattr(m, name)
        except AttributeError:
            continue
    raise AttributeError(f"module 'stanok' has no attribute {name!r}")


if __name__ == "__main__":
    import cli
    raise SystemExit(cli.main())
