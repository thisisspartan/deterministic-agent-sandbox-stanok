#!/usr/bin/env python3
"""Stanok 4.2 Production — Context-Engineered Runner on a local model.

Full integration with the L1 Supervisor:
  1. Single Continuous Session (ClaudeSDKClient): retries inside ONE session (99% KV cache).
  2. Strict summary.json contract (probe_result, c5, review_verdict, errors) for L1.
  3. Adaptive Contract Lock: adaptation for creating tests from scratch and a ban on weakening assertions.
  4. Cumulative Token & Cache Telemetry: exact session_hit_rate calculation.
  5. Shielded Turn Watchdog: the turn timeout (default 1200s) is a terminal DoS
     circuit breaker — asyncio.shield() keeps the turn task alive past wait_for,
     so client.interrupt() runs cleanly and summary.json is written with the
     TURN-TIMEOUT code (rc=1) without the process dying on CancelledError.
  6. Smart Diff Extraction: prioritized assert/diff search with a UTF-8 slice.
  7. Process Reaper: a single process group with guaranteed termination of all children.
"""

import argparse
import asyncio
import dataclasses
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import sandbox  # R2: the Docker boundary (former sandbox-run.sh)

# --- Circuit constants -------------------------------------------------------------
LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
# If STANOK_REPO is not set, we go up one level (stanok/launcher -> stanok)
DEFAULT_REPO = os.path.abspath(os.path.join(LAUNCHER_DIR, ".."))
REPO_ROOT = os.path.abspath(os.environ.get("STANOK_REPO", DEFAULT_REPO))
LOG_DIR = os.environ.get("STANOK_LOG_DIR", "/tmp/stanok-logs")
os.makedirs(LOG_DIR, exist_ok=True)

DEFAULT_MODEL = "Qwen3.8-27B-MTP"
LOCAL_MODEL = os.environ.get("STANOK_MODEL", DEFAULT_MODEL)
SERVER_URL = os.environ.get("STANOK_SERVER_URL", "http://127.0.0.1:8080")
CLAUDE_BIN = os.environ.get("STANOK_CLAUDE_BIN", shutil.which("claude") or "claude")

MAX_TEST_LINES = 60
MAX_TEST_BYTES = 4096
DEFAULT_RETRIES = int(os.environ.get("STANOK_LOCAL_RETRIES", "2"))

API_TIMEOUT_S = max(1.0, float(os.environ.get("STANOK_API_TIMEOUT_S", "600")))
TURN_TIMEOUT_S = float(os.environ.get("STANOK_TURN_TIMEOUT_S", "1800"))

if TURN_TIMEOUT_S <= API_TIMEOUT_S:
    TURN_TIMEOUT_S = API_TIMEOUT_S + max(15.0, API_TIMEOUT_S * 0.2)

API_TIMEOUT_MS = str(int(API_TIMEOUT_S * 1000))
# Native Bash replaces the old MCP `run` tool (Docker refactor): the model
# runs `bash scripts/run.sh {list,test,smoke}` directly; the boundary is the
# container, not a per-command allowlist.
CURATED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]

_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_FILE_LINE_RE = re.compile(r"^(impl|test|docs):\s*([A-Za-z0-9_./-]+)\s*$")
_RESET_NONE_RE = re.compile(r"^reset:\s*none\s*$", re.IGNORECASE)
_DECLARED_ZONES = ("src", "tests", "docs", "scripts")

_stdout_log_f = None
_marker_path = None
_evidence_dir = None
_live_dir = None
_INTERRUPTED_RC = 0


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
    return (os.path.join(REPO_ROOT, "evidence", label), os.path.join(LOG_DIR, label))


# ==================================================================================
# Sanitary control and gates
# ==================================================================================
def validate_label(label: str) -> str | None:
    if not _LABEL_RE.match(label) or ".." in label or label.startswith("--"):
        return f"label {label!r} contains invalid characters"
    return None


def root_refusal() -> None:
    if os.geteuid() == 0:
        log("ABORT: running as root is forbidden")
        sys.exit(1)


def dirty_tree_gate() -> bool:
    # Fail-closed: a git error means the tree state is UNKNOWN -> treat as dirty.
    try:
        out = subprocess.run(["git", "status", "--porcelain"],
                             cwd=REPO_ROOT, capture_output=True, text=True)
        if out.returncode != 0:
            log("WARN: git status failed in dirty_tree_gate — fail-closed (treating as dirty)")
            return True
        return bool(out.stdout.strip())
    except OSError:
        log("WARN: git status raised in dirty_tree_gate — fail-closed (treating as dirty)")
        return True


def _required_context_window() -> int | None:
    """Required context window: env STANOK_REQUIRED_WINDOW overrides
    CLAUDE_CODE_AUTO_COMPACT_WINDOW from .claude/settings.stanok.json."""
    env_val = os.environ.get("STANOK_REQUIRED_WINDOW")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            log(f"WARN: STANOK_REQUIRED_WINDOW={env_val!r} is not an integer; ignoring")
    try:
        with open(os.path.join(REPO_ROOT, ".claude", "settings.stanok.json"), encoding="utf-8") as f:
            val = json.load(f).get("env", {}).get("CLAUDE_CODE_AUTO_COMPACT_WINDOW")
        if val is not None:
            return int(val)
    except (OSError, ValueError):
        pass
    return None


def context_rot_threshold() -> int:
    """Warn threshold for the live context window (tokens on the LAST API call).
    Env STANOK_CONTEXT_ROT_TOKENS wins; otherwise 80% of the compaction window —
    the point where attention on a long prompt visibly degrades."""
    env = os.environ.get("STANOK_CONTEXT_ROT_TOKENS")
    if env:
        try:
            return int(env)
        except ValueError:
            log(f"WARN: STANOK_CONTEXT_ROT_TOKENS={env!r} is not an integer; ignoring")
    window = _required_context_window() or 128000
    return int(window * 0.8)


def preflight_server() -> bool:
    if os.environ.get("STANOK_SKIP_SERVER_CHECK") == "1":
        return True
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(f"{SERVER_URL}/props"), timeout=5) as resp:
            props = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        log(f"SERVER UNAVAILABLE ({SERVER_URL}: {type(e).__name__}) (rc=20)")
        return False

    required = _required_context_window()
    if required is None:
        log("PREFLIGHT: server reachable, no required window configured — OK")
        return True

    n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
    if not isinstance(n_ctx, int) or n_ctx <= 0:
        log(f"PREFLIGHT: unparseable n_ctx in /props (fail-closed) (rc=20)")
        return False
    if n_ctx < required:
        log(f"PREFLIGHT: server n_ctx={n_ctx} < required window {required} (rc=20)")
        return False
    log(f"PREFLIGHT: server n_ctx={n_ctx} >= required window {required} — OK")
    return True


def _opik_trace_count() -> int | None:
    """Total trace count in the 'stanok' Opik project, or None if Opik is
    unreachable. The machine exports OTLP spans to the host Opik backend
    (network=host -> localhost:8080). We sample the count before and after a
    run: the delta is this run's exported traces. A delta of 0 (or an
    unreachable backend) means the run left no traces — surfaced loudly so a
    silent 'no traces' can never happen again."""
    if os.environ.get("STANOK_SKIP_OPIK_CHECK") == "1":
        return None
    base = os.environ.get("STANOK_OPIK_URL", "http://localhost:8080")
    url = f"{base}/v1/private/traces?project_name=stanok&limit=1"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(url), timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        total = data.get("total")
        return total if isinstance(total, int) else None
    except Exception:
        return None


def _validate_declared_path(rel: str) -> bool:
    """Literal `files:` paths are ticket-supplied input: prepare_workspace's
    quarantine shutil.move()s them, so an unvalidated path (e.g. `impl:
    /etc/passwd`) could destroy arbitrary host files. Fail-closed: relative,
    no `..` segments, top-level dir inside the writable zones."""
    if rel.startswith("/") or rel.startswith("./"):
        return False
    if ".." in rel.split("/"):
        return False
    return rel.split("/", 1)[0] in _DECLARED_ZONES


def parse_ticket_header(ticket_text: str) -> tuple[list[str], bool]:
    """Ticket-scoped invariant (W2.1): the header is the leading block of
    literal `impl: <path>` / `test: <path>` / `docs: <path>` lines plus an
    optional `reset: none` escape hatch for extension tickets. `#` title
    lines and blank lines are skipped inside the header block; the first
    other line ends it (a path mentioned in the body is never matched).
    Paths are validated (relative, no `..`, inside src/tests/docs/scripts);
    an invalid path raises ValueError (fail-closed, rc=13 upstream).
    Returns (declared_paths, reset_none)."""
    declared: list[str] = []
    reset_none = False
    for line in ticket_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _FILE_LINE_RE.match(stripped)
        if m:
            rel = m.group(2)
            if not _validate_declared_path(rel):
                raise ValueError(
                    f"invalid declared path {rel!r}: must be relative, contain no "
                    f"'..', and start with one of {list(_DECLARED_ZONES)}"
                )
            declared.append(rel)
            continue
        if _RESET_NONE_RE.match(stripped):
            reset_none = True
            continue
        break
    return declared, reset_none


def prepare_workspace(declared_paths: list[str]) -> int:
    # SEC-01: .git is read-only inside the container — NO git writes here.
    # The cleanliness gate is dirty_tree_gate() (single source, called by main()
    # rc=22 and by launch.sh via `check-dirty`). This function only prepares the
    # writable workspace.
    try:
        for d in ("src", "tests", "docs", "scripts"):
            os.makedirs(os.path.join(REPO_ROOT, d), exist_ok=True)
        # Ticket-scoped invariant (W2.2): QUARANTINE (not delete) the artifacts
        # the ticket declares, so the run starts in a state where they do not
        # exist. Non-destructive: moved to _live_dir/pre-existing/ (outside the
        # repo — dirty_tree_gate is unaffected). Called ONCE before the session:
        # retries never wipe the model's work.
        quarantined = []
        for rel in declared_paths:
            src_path = os.path.join(REPO_ROOT, rel)
            if not os.path.exists(src_path):
                continue
            dest = os.path.join(_live_dir, "pre-existing", rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src_path, dest)
            quarantined.append(rel)
        if quarantined:
            log(f"QUARANTINE: {len(quarantined)} pre-existing declared path(s) "
                f"moved to {_live_dir}/pre-existing/: {quarantined}")
        return 0
    except OSError as e:
        log(f"ERROR: repo prep failed: {e}")
        return 14


# ==================================================================================
# Smart compression of verifier errors (Smart Diff Extraction)
# ==================================================================================
def _extract_smart_diff(raw_text: str) -> str:
    cleaned_lines = [
        line for line in raw_text.strip().splitlines()
        if "node_modules/" not in line
    ]
    if not cleaned_lines:
        cleaned_lines = raw_text.strip().splitlines()

    if len(cleaned_lines) <= MAX_TEST_LINES:
        res = "\n".join(cleaned_lines)
    else:
        high_pri = re.compile(
            r"(assertionerror|strictequal|deepstrictequal|expected|actual|not ok\s+\d+"
            r"|#\s+fail\s+\d+|diff:|traceback \(most recent call last\)|^\s*e\s+assert)",
            re.I)
        matches = [i for i, line in enumerate(cleaned_lines) if high_pri.search(line)]

        if not matches:
            low_pri = re.compile(r"(fail|assert|error:)", re.I)
            matches = [i for i, line in enumerate(cleaned_lines) if low_pri.search(line)]

        if matches:
            center = matches[-1]
            start = max(0, center - 20)
            end = min(len(cleaned_lines), start + MAX_TEST_LINES)
            if end - start < MAX_TEST_LINES:
                start = max(0, end - MAX_TEST_LINES)
            window = cleaned_lines[start:end]
            hdr = [f"... [{start} lines skipped above] ..."] if start > 0 else []
            ftr = [f"... [{len(cleaned_lines) - end} lines skipped below] ..."] if end < len(cleaned_lines) else []
            res = "\n".join(hdr + window + ftr)
        else:
            # Mandatory fallback (P6): no specific pattern matched — keep the
            # last 25 lines of the test output (the failure is at the tail).
            start = max(0, len(cleaned_lines) - 25)
            hdr = [f"... [{start} lines skipped above] ..."] if start > 0 else []
            res = "\n".join(hdr + cleaned_lines[start:])

    b_res = res.encode("utf-8")
    if len(b_res) > MAX_TEST_BYTES:
        res = b_res[:MAX_TEST_BYTES].decode("utf-8", errors="ignore") + "\n... [output truncated at the byte limit] ..."
    return res


def _run_one_test(rel: str) -> tuple[str, str] | None:
    """Run one test through the project's declared entrypoint (D3).

    The machine does not own the test invocation: it calls scripts/run.sh,
    exactly as the model's Bash tool does. Any runner flags (node/--test/...)
    live inside run.sh, so all call sites agree by construction.
    """
    try:
        p = subprocess.run(["bash", "scripts/run.sh", "test", rel],
                           cwd=REPO_ROOT, capture_output=True, text=True, timeout=90)
        if p.returncode != 0:
            raw_err = (p.stderr or "") + "\n" + (p.stdout or "")
            return (rel, _extract_smart_diff(raw_err))
    except subprocess.TimeoutExpired:
        return (rel, "TIMEOUT: test execution exceeded the runner limit")
    except Exception as e:
        return (rel, f"EXEC_ERROR: {e}")
    return None


def verify_gate(declared_paths: list[str] | None = None) -> tuple[bool, list[tuple[str, str]]]:
    """Verdict = positive contract on the ticket's declared paths (W2.3)
    + every test the project's runner declares (D3).

    Discovery goes through the project entrypoint too (run.sh list), so the
    machine no longer hardcodes the *.test.js convention.
    """
    failures: list[tuple[str, str]] = []
    # Positive contract: every artifact the ticket declares must exist.
    # Closes the hole where a model that skipped docs/<m>.md still passed.
    for rel in (declared_paths or []):
        if not os.path.exists(os.path.join(REPO_ROOT, rel)):
            failures.append((rel, f"MISSING: declared by the ticket but not created: {rel}"))

    try:
        lp = subprocess.run(["bash", "scripts/run.sh", "list"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return (False, [("(no tests)", f"run.sh list failed: {e}")])
    tests = [ln.strip() for ln in (lp.stdout or "").splitlines() if ln.strip()]
    if not tests:
        if failures:
            return (False, failures)
        return (False, [("(no tests)", "The project runner declares no tests")])

    with ThreadPoolExecutor(max_workers=min(8, len(tests))) as ex:
        futures = {ex.submit(_run_one_test, t): t for t in tests}
        for fut in as_completed(futures):
            res = fut.result()
            if res is not None:
                failures.append(res)
    failures.sort(key=lambda x: x[0])
    return (len(failures) == 0, failures)


def _tests_manifest() -> dict[str, str]:
    """Snapshot {rel_path: sha256} of tests/ + scripts/run.sh (contract_lock,
    W2.5 + P2). Only PRE-EXISTING files are snapshotted: a missing
    scripts/run.sh (bootstrap of a new project) is therefore free to create."""
    manifest: dict[str, str] = {}
    tests_dir = os.path.join(REPO_ROOT, "tests")
    if os.path.isdir(tests_dir):
        for root, _dirs, files in os.walk(tests_dir):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, REPO_ROOT)
                try:
                    with open(full, "rb") as f:
                        manifest[rel] = hashlib.sha256(f.read()).hexdigest()
                except OSError:
                    manifest[rel] = "unreadable"
    runsh = os.path.join(REPO_ROOT, "scripts", "run.sh")
    if os.path.isfile(runsh):
        try:
            with open(runsh, "rb") as f:
                manifest["scripts/run.sh"] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            manifest["scripts/run.sh"] = "unreadable"
    return manifest


def _check_contract_lock(before: dict[str, str], job: dict, turn: int,
                         declared_paths: list[str] | None = None) -> None:
    """After each turn: a pre-existing protected file (tests/, scripts/run.sh)
    that was MODIFIED or DELETED is a contract_lock violation (replaces the
    chmod a-w freeze, W2.5). New files are allowed (a ticket may declare
    several). scripts/run.sh is exempt when the ticket declares it
    (runner-update ticket, P2)."""
    after = _tests_manifest()
    declared = set(declared_paths or [])
    violations = []
    for rel, digest in before.items():
        if rel == "scripts/run.sh" and rel in declared:
            continue
        if rel not in after:
            violations.append(f"DELETED: {rel}")
        elif after[rel] != digest:
            violations.append(f"MODIFIED: {rel}")
    if violations:
        job.setdefault("contract_lock_violations", []).extend(
            f"turn {turn}: {v}" for v in violations
        )
        log(f"  [CONTRACT-LOCK] turn {turn}: {violations}")


# ==================================================================================
# Inference environment (Prefix Invariance)
# ==================================================================================
def build_agent_env() -> dict[str, str]:
    """Runtime-only env for the machine process.

    Static machine config lives in `.claude/settings.stanok.json` -> `env`, which
    claude applies natively at startup via `Object.assign(process.env,
    settings.env)` (cli.js `jUK()`). That assignment runs AFTER the SDK has set
    this dict, so any key present in BOTH would silently win from settings and
    kill the runtime knob. Hence: only derive-from-runtime keys belong here
    (endpoint, model, timeout); everything static belongs in settings.

    No proxy: the machine has no web tools (CURATED_TOOLS) and its only outbound
    is the local API server, which is directly reachable. Native sandbox injects
    its own proxy env into Bash commands when network.allowedDomains is set.
    """
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "ANTHROPIC_BASE_URL": SERVER_URL,
        "ANTHROPIC_MODEL": LOCAL_MODEL,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": LOCAL_MODEL,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": LOCAL_MODEL,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": LOCAL_MODEL,
        "CLAUDE_CODE_SUBAGENT_MODEL": LOCAL_MODEL,
        "API_TIMEOUT_MS": API_TIMEOUT_MS,
    }


# ==================================================================================
# Continuous ClaudeSDKClient session + Shielded Watchdog
# ==================================================================================
def _extract_usage(msg) -> dict:
    usage = getattr(msg, "usage", None)
    if not usage and hasattr(msg, "data") and isinstance(msg.data, dict):
        usage = msg.data.get("usage")
    if not usage:
        return {}
    if dataclasses.is_dataclass(usage):
        return dataclasses.asdict(usage)
    if hasattr(usage, "__dict__"):
        return {k: v for k, v in usage.__dict__.items() if not k.startswith("_")}
    if isinstance(usage, dict):
        return usage
    return {}


async def _execute_turn(client, prompt: str, turn: int, stream_f, job: dict, local_run_id: str) -> tuple[dict, dict, int, str]:
    """Returns (turn_total, live_window, writes).

    turn_total  — ResultMessage.usage: cumulative across the turn's API calls
                  (for session totals).
    live_window — the last AssistantMessage.usage: the prompt size actually sent
                  on the final API call (the true context window, for CONTEXT-ROT).
    writes      — count of Write/Edit tool_use blocks in the turn (NO-OP assert,
                  W2.4; immune to test side effects, unlike a file manifest).
    """
    from claude_agent_sdk import ResultMessage

    await client.query(prompt)
    live_window = {}
    turn_total = {}
    writes = 0
    turn_error = ""
    async for msg in client.receive_response():
        sid = getattr(msg, "session_id", None)
        if not sid and hasattr(msg, "data") and isinstance(msg.data, dict):
            sid = msg.data.get("session_id")
        if sid and not job.get("session_id"):
            job["session_id"] = str(sid)

        u = _extract_usage(msg)
        if u:
            if isinstance(msg, ResultMessage):
                turn_total = u
            else:
                live_window = u

        # A ResultMessage with is_error=True (e.g. "API Error: terminated" or
        # "API Error: 503 Loading model") means the SDK session is dead: further
        # queries on it return a stale 0-token result instantly. Capture the
        # reason so the caller can stop instead of burning the remaining turns
        # on a dead session. is_error/result are direct dataclass fields.
        if isinstance(msg, ResultMessage):
            is_err = getattr(msg, "is_error", None)
            res = getattr(msg, "result", None)
            data = getattr(msg, "data", None)
            if isinstance(data, dict):
                is_err = is_err or data.get("is_error")
                res = res or data.get("result")
            if is_err:
                turn_error = str(res or "unknown API error")

        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                if getattr(block, "name", None) in ("Write", "Edit"):
                    writes += 1

        _write_stream_msg(stream_f, turn, msg)
    return (turn_total or live_window), live_window, writes, turn_error


# R1 (Phase 2): in-process replacement for hooks/verifier.sh.
# PostToolUse on Write|Edit: if the written file is a test under tests/ and it
# runs RED through the project entrypoint, inject "VERIFY: RED CONFIRMED" so
# the model goes straight to the implementation.
#
# Runs as an SDK hook callback (CLI hook_callback control channel), NOT a
# shell command: no jq, no bash hook process in the trace. The subprocess is
# asyncio.create_subprocess_exec — a sync subprocess here would block the
# event loop that also runs the turn watchdog. Fail-open, exactly like the
# old shell hook: ANY error in this callback yields a no-op, never a failed
# turn (the external verifier is the fail-closed gate; this is feedback only).
_HOOK_TEST_TIMEOUT_S = 75  # mirrors the old `timeout 75` in verifier.sh


async def _verifier_hook(hook_input: dict, tool_use_id: "str | None", context) -> dict:
    try:
        tool_input = hook_input.get("tool_input") or {}
        fp = tool_input.get("file_path")
        if not fp:
            return {}
        if not fp.startswith("/"):
            fp = os.path.join(REPO_ROOT, fp)
        abs_path = os.path.realpath(fp)
        tests_dir = os.path.join(REPO_ROOT, "tests")
        if not abs_path.startswith(tests_dir + os.sep):
            return {}
        if not os.path.isfile(abs_path):
            return {}
        run_sh = os.path.join(REPO_ROOT, "scripts", "run.sh")
        if not os.path.isfile(run_sh):
            return {}
        rel = os.path.relpath(abs_path, REPO_ROOT)
        proc = await asyncio.create_subprocess_exec(
            "bash", run_sh, "test", rel,
            cwd=REPO_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=_HOOK_TEST_TIMEOUT_S)
            rc = proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            rc, out = 124, b""
        # rc=0: GREEN (implementation exists) — stay silent.
        # rc=2: runner refused the path (not a test in its terms) — not our concern.
        if rc in (0, 2):
            return {}
        text = out.decode("utf-8", "replace")
        tail = "\n".join(text.splitlines()[-25:])
        log(f"VERIFIER HOOK: RED CONFIRMED ({rel} rc={rc})")
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"VERIFY: RED CONFIRMED ({rel} rc={rc}). "
                    f"Implement src/ to make it GREEN.\n{tail}"
                ),
            }
        }
    except Exception as e:
        log(f"VERIFIER HOOK: no-op (error: {e})")
        return {}


async def run_continuous_session(job: dict, ticket_prompt: str, max_retries: int, declared_paths: list[str]) -> int:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher

    local_run_id = str(uuid.uuid4())[:8]
    stream_out_path = os.path.join(_live_dir, f"session-{local_run_id}.jsonl")

    options = ClaudeAgentOptions(
        cli_path=CLAUDE_BIN,
        cwd=REPO_ROOT,
        setting_sources=["project"],
        settings=f"{REPO_ROOT}/.claude/settings.stanok.json",
        permission_mode="dontAsk",
        # R3: `tools` -> `--tools` restricts the session's tool surface to
        # exactly CURATED_TOOLS (the CLI's default set is NOT added on top);
        # allowed_tools is kept as the permission-allow side of the same set.
        tools=CURATED_TOOLS,
        allowed_tools=CURATED_TOOLS,
        # R1: in-process PostToolUse verifier (replaces hooks/verifier.sh).
        # timeout > _HOOK_TEST_TIMEOUT_S so the hook's own 75 s test timeout
        # is the deterministic verdict, not the SDK's hook timeout.
        hooks={
            "PostToolUse": [
                HookMatcher(matcher="Write|Edit", hooks=[_verifier_hook], timeout=90)
            ]
        },
        max_turns=30,
        model=LOCAL_MODEL,
        env=build_agent_env(),
    )

    max_turns = 1 + max_retries
    current_prompt = ticket_prompt
    log(f"SESSION START (run_id: {local_run_id}) | Turn limit: {max_turns} | model={LOCAL_MODEL}")

    total_tokens = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    job["tokens"] = total_tokens
    job["cache_hit_rate"] = "0.0%"

    # contract_lock (W2.5): snapshot tests/ before the session; a pre-existing
    # test file modified/deleted during the run is a violation in summary.json.
    tests_manifest_before = _tests_manifest()

    with open(stream_out_path, "a", encoding="utf-8") as stream_f:
        async with ClaudeSDKClient(options=options) as client:
            for turn in range(1, max_turns + 1):
                log(f"\n>>> Turn {turn}/{max_turns} {'(Fixing errors in src/)' if turn > 1 else '(Ticket start)'} <<<")

                t0 = time.time()
                turn_task = asyncio.create_task(
                    _execute_turn(client, current_prompt, turn, stream_f, job, local_run_id)
                )

                try:
                    turn_usage, live_window, turn_writes, turn_error = await asyncio.wait_for(asyncio.shield(turn_task), timeout=TURN_TIMEOUT_S)
                except asyncio.TimeoutError:
                    log(f"TIMEOUT: turn {turn} exceeded {TURN_TIMEOUT_S:.0f}s (silent stall) -> interrupt")
                    try:
                        await client.interrupt()
                    except Exception as e:
                        log(f"WARN: client.interrupt() finished with an error: {e}")

                    try:
                        await asyncio.wait_for(asyncio.shield(turn_task), timeout=5.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass
                    if not turn_task.done():
                        turn_task.cancel()
                    await asyncio.gather(turn_task, return_exceptions=True)

                    job["error"] = f"TURN-TIMEOUT ({TURN_TIMEOUT_S:.0f}s)"
                    job["verifier"] = "FAIL"
                    job["turns"] = turn
                    return 1

                elapsed_turn = time.time() - t0

                inp = turn_usage.get("input_tokens", 0)
                out = turn_usage.get("output_tokens", 0)
                c_read = turn_usage.get("cache_read_input_tokens", 0)
                c_create = turn_usage.get("cache_creation_input_tokens", 0)

                total_tokens["input_tokens"] += inp
                total_tokens["output_tokens"] += out
                total_tokens["cache_read_input_tokens"] += c_read
                total_tokens["cache_creation_input_tokens"] += c_create

                total_input_context = (
                    total_tokens["input_tokens"]
                    + total_tokens["cache_read_input_tokens"]
                    + total_tokens.get("cache_creation_input_tokens", 0)
                )
                session_hit_rate = (
                    total_tokens["cache_read_input_tokens"] / total_input_context * 100.0
                ) if total_input_context > 0 else 0.0
                job["tokens"] = total_tokens
                job["cache_hit_rate"] = f"{session_hit_rate:.1f}%"

                turn_input_context = inp + c_read + c_create
                turn_hit_rate = (c_read / turn_input_context * 100.0) if turn_input_context > 0 else 0.0

                # Live window = prompt size on the LAST API call (not the turn's
                # cumulative usage) — the real context the model had to attend to.
                live_context = (
                    live_window.get("input_tokens", 0)
                    + live_window.get("cache_read_input_tokens", 0)
                    + live_window.get("cache_creation_input_tokens", 0)
                ) or turn_input_context

                log(f"Turn {turn} finished in {elapsed_turn:.1f}s | "
                    f"Turn tokens: in={inp}, out={out}, cache_hit={c_read} ({turn_hit_rate:.1f}%) | "
                    f"live window: {live_context} | "
                    f"Session cache_hit: {session_hit_rate:.1f}%")

                job.setdefault("turn_telemetry", []).append({
                    "turn": turn,
                    "elapsed_s": round(elapsed_turn, 1),
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_read_input_tokens": c_read,
                    "cache_creation_input_tokens": c_create,
                    "live_context_tokens": live_context,
                    "turn_hit_rate": round(turn_hit_rate, 1),
                    "writes": turn_writes,
                })

                # A turn that ended with an SDK API error (e.g. "API Error:
                # terminated" — the model server dropped the connection) leaves
                # the session dead: subsequent fix prompts return a stale
                # 0-token result instantly and waste the remaining turns. Stop
                # the run now with a clear error; the supervisor relaunches.
                if turn_error:
                    log(f"TURN {turn} ended with API error: {turn_error!r} — "
                        f"session dead, stopping (no fix prompt)")
                    job["error"] = f"TURN-{turn} API ERROR: {turn_error}"
                    job["verifier"] = "FAIL"
                    job["turns"] = turn
                    return 1

                # contract_lock (W2.5 + P2): did the turn touch pre-existing
                # tests/ or scripts/run.sh?
                _check_contract_lock(tests_manifest_before, job, turn, declared_paths)

                # PREFIX-BREAK alarm: a KV-prefix break shows up exactly as a
                # spike in the turn's input_tokens (uncached re-send).
                prev_inputs = [t["input_tokens"] for t in job["turn_telemetry"][:-1]]
                if prev_inputs:
                    median_prev = sorted(prev_inputs)[len(prev_inputs) // 2]
                    if inp > 2 * median_prev:
                        job["turn_telemetry"][-1]["prefix_break"] = True
                        log(f"  [PREFIX-BREAK WARN] turn {turn} input_tokens={inp} "
                            f"> 2x median of previous turns ({median_prev}) — KV prefix likely not reused")
                elif inp > 4000:
                    job["turn_telemetry"][-1]["prefix_break"] = True
                    log(f"  [PREFIX-BREAK WARN] turn {turn} input_tokens={inp} > 4000 baseline")

                rot_threshold = context_rot_threshold()
                if live_context > rot_threshold:
                    log(f"  [CONTEXT-ROT WARN] Live context window ({live_context} tokens) "
                        f"exceeded the threshold {rot_threshold}. Model attention may degrade.")

                verify_ok, failures = verify_gate(declared_paths)

                if verify_ok:
                    # NO-OP assert (W2.4): a turn-1 pass with zero Write/Edit
                    # tool_use means the machine did no work — the artifacts
                    # pre-existed. rc=1 (defect); no new rc code is introduced.
                    if turn == 1 and turn_writes == 0:
                        log("NO-OP-PASS: verifier passed on turn 1 with zero "
                            "Write/Edit calls — the machine did no work")
                        job["verifier"] = "PASS"
                        job["probe_result"] = "NO-OP-PASS"
                        job["turns"] = turn
                        return 1
                    log("VERIFIER: PASS — All tests passed successfully!")
                    job["verifier"] = "PASS"
                    job["turns"] = turn
                    return 0

                log(f"VERIFIER: FAIL — Failed tests: {len(failures)}")
                job["failures"] = failures

                if turn < max_turns:
                    has_no_tests = any(name == "(no tests)" for name, _ in failures)

                    if has_no_tests:
                        rules = (
                            "1. There are no test files in the tests/ directory! Create the reference tests strictly per the ticket specification.\n"
                            "2. Then implement the corresponding working module code in the src/ directory."
                        )
                    else:
                        rules = (
                            "1. The tests in tests/ are the reference specification of the ticket. It is CATEGORICALLY FORBIDDEN to delete, modify, or weaken assertions in tests/.\n"
                            "2. Fixes are made EXCLUSIVELY in the module implementations in the src/ directory.\n"
                            "3. Study the diff and stack above, localize the error in src/ and eliminate the root cause of the bug."
                        )

                    fail_xml_blocks = "\n".join([
                        f'  <failure test="{name}">\n{diff}\n  </failure>'
                        for name, diff in failures
                    ])
                    current_prompt = (
                        f"<verification_result status=\"FAIL\" turn=\"{turn}\">\n"
                        f"<test_errors count=\"{len(failures)}\">\n"
                        f"{fail_xml_blocks}\n"
                        f"</test_errors>\n"
                        f"<contract_lock>\n"
                        f"{rules}\n"
                        f"</contract_lock>\n"
                        f"</verification_result>"
                    )
                else:
                    log("Retry limit exhausted (Context Inertia Guard). Finishing.")

    job["verifier"] = "FAIL"
    job["turns"] = max_turns
    return 1


# ==================================================================================
# Processes, signals, and artifacts
# ==================================================================================
def _install_signal_handlers() -> None:
    def handler(signum, _frame):
        global _INTERRUPTED_RC
        _INTERRUPTED_RC = 128 + signum
        log(f"\nSIGNAL {signum}: Run interrupted. Stopping child processes...")
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            os.killpg(0, signal.SIGTERM)
        except OSError:
            pass
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def _status_fields(rc: int, verifier: str, turns: int) -> tuple[str, str, str]:
    """RC_TABLE — single source of the status fields, derived from
    (rc, verifier, turns). A new outcome = one row here.
    Fail-closed: only rc==0 AND verifier=="PASS" is a pass; everything
    else is a defect (no PASS-on-FAIL)."""
    if rc == 0 and verifier == "PASS":
        probe_result = "CLEAN-FIRST" if turns == 1 else "PASS-AFTER-LOCAL-RETRY"
        return probe_result, "PASS", "CLEAN"
    return "VERIFY-FAIL", "FAIL", "DEFECT"


def build_summary(job: dict, elapsed_s: int) -> dict:
    """Single source of the summary.json schema (shared by write_summary
    and early_abort)."""
    turns = job.get("turns", 1)
    verifier = job.get("verifier", "FAIL")
    rc = job.get("rc", 1)
    probe_result, c5, review_verdict = _status_fields(rc, verifier, turns)
    if job.get("probe_result"):
        probe_result = job["probe_result"]
        # rc=1 is polysemous: NO-OP-PASS vs exhausted-retries. Disambiguate by
        # probe_result, NOT rc — the rc->fields table cannot express two field
        # sets for one rc, so _status_fields is not a pure function of rc (the
        # probe_result override above already broke that); do not "restore" a
        # pure rc->fields table. A NO-OP is a success: verify_gate really
        # passed (c5=PASS is a fact), and review_verdict is the third outcome
        # (NOOP) — neither CLEAN (no build) nor DEFECT (no defect).
        if probe_result == "NO-OP-PASS":
            c5 = "PASS"
            review_verdict = "NOOP"

    per_turn = job.get("turn_telemetry", [])
    inference_telemetry = {
        "per_turn": per_turn,
        "aggregate": {
            "turns": len(per_turn),
            "total_turn_elapsed_s": round(sum(t.get("elapsed_s", 0) for t in per_turn), 1),
            "tokens": job.get("tokens", {}),
            "cache_hit_rate": job.get("cache_hit_rate", "0.0%"),
        },
    }

    # Provenance (W2.6): the exact commit the run started from.
    commit_sha = None
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            commit_sha = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

    return {
        "label": job.get("label"),
        "ticket": job.get("ticket"),
        "rc": rc,
        "verifier": verifier,
        "probe_result": probe_result,
        "review_verdict": review_verdict,
        "c5": c5,
        "turns": turns,
        "elapsed_s": elapsed_s,
        "session_id": job.get("session_id"),
        "commit_sha": commit_sha,
        "tokens": job.get("tokens", {}),
        "cache_hit_rate": job.get("cache_hit_rate", "0.0%"),
        "inference_telemetry": inference_telemetry,
        "contract_lock_violations": job.get("contract_lock_violations", []),
        "errors": [job["error"]] if job.get("error") else [],
        "failures": job.get("failures", []),
        "opik_traces": job.get("opik_traces"),
    }


def write_summary(job: dict, elapsed_s: int) -> None:
    """Writes the exact summary.json contract expected by the L1 Supervisor."""
    with open(os.path.join(_evidence_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(build_summary(job, elapsed_s), f, ensure_ascii=False, indent=2)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cmd_run(args) -> int:
    global _stdout_log_f, _marker_path, _evidence_dir, _live_dir

    try:
        if os.getpgid(0) != os.getpid():
            os.setpgid(0, 0)
    except OSError:
        pass

    _evidence_dir, _live_dir = label_paths(args.label)
    os.makedirs(_evidence_dir, exist_ok=True)
    os.makedirs(_live_dir, exist_ok=True)

    _stdout_log_f = open(os.path.join(_evidence_dir, "launcher.stdout.log"), "a", encoding="utf-8")
    _marker_path = os.path.join(_evidence_dir, ".running")

    start_ts = int(time.time())
    recorded_pid = os.getpid()

    # R2: the marker is written by the host-side supervisor (run_sandboxed /
    # launch_background) with ITS pid — inside the container os.getpid() is
    # not visible from the host. If the marker already exists, preserve its
    # start_ts/pid; only a fresh in-process run (no-sandbox) writes its own.
    if os.path.exists(_marker_path):
        try:
            parts = open(_marker_path, "r", encoding="utf-8").read().split()
            if len(parts) >= 2:
                start_ts = int(parts[0])
                recorded_pid = int(parts[1])
        except (ValueError, OSError):
            pass

    with open(_marker_path, "w", encoding="utf-8") as f:
        f.write(f"{start_ts} {recorded_pid}\n")

    _install_signal_handlers()

    job = {"label": args.label, "ticket": args.ticket}
    log(f"STANOK 4.2 RUNNER | Repo: {REPO_ROOT} | Label: {args.label}")
    if args.direct:
        log("--direct MODE: the ticket path is resolved relative to the repository")

    # Ticket-scoped invariant (W2.1): parse the header BEFORE any workspace
    # mutation. Fail-closed: no `impl:`/`test:`/`docs:` line and no
    # `reset: none` means the invariant cannot be enforced (the old false
    # CLEAN-FIRST returns); an invalid literal path is rejected the same way.
    try:
        with open(args.ticket_path, encoding="utf-8") as f:
            ticket_prompt = f.read().strip()
        declared_paths, reset_none = parse_ticket_header(ticket_prompt)
    except (OSError, ValueError) as e:
        job["rc"] = 13
        job["error"] = f"ticket parse error: {e}"
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 13

    if not declared_paths and not reset_none:
        job["rc"] = 13
        job["error"] = ("ticket declares no `impl:`/`test:`/`docs:` line and no "
                        "`reset: none` — the ticket-scoped invariant cannot be "
                        "enforced (fail-closed)")
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 13
    if declared_paths:
        log(f"DECLARED PATHS: {declared_paths}")

    if not preflight_server():
        job["rc"] = 20
        job["error"] = f"Server unavailable ({SERVER_URL})"
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 20

    if prepare_workspace(declared_paths) != 0:
        job["rc"] = 14
        job["error"] = "workspace prep error"
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 14

    # Opik trace verification (baseline): sample the project trace count before
    # the run. The delta after the run is this run's exported traces — one run
    # at a time (the lock guarantees no concurrent stanok run to pollute it).
    opik_before = _opik_trace_count()
    if opik_before is None:
        log("OPIK: backend unreachable — traces will NOT be recorded for this run")
    else:
        log(f"OPIK: backend reachable (project trace baseline={opik_before})")

    rc = 1
    try:
        rc = asyncio.run(run_continuous_session(job, ticket_prompt, args.local_retries, declared_paths))
    except KeyboardInterrupt:
        rc = _INTERRUPTED_RC or 130
    except Exception as e:
        log(f"FATAL EXCEPTION: {e}")
        job["error"] = str(e)
        rc = 1
    finally:
        job["rc"] = rc
        # Post-run Opik check: how many traces did this run export? OTLP export
        # is batched/async, so if the count has not moved yet, give it a short
        # settle and re-sample once before concluding.
        opik_after = _opik_trace_count()
        if opik_before is None or opik_after is None:
            job["opik_traces"] = None
            log("OPIK: post-run trace count unavailable (backend unreachable)")
        else:
            if opik_after <= opik_before:
                time.sleep(3)
                resample = _opik_trace_count()
                if resample is not None:
                    opik_after = resample
            delta = opik_after - opik_before
            job["opik_traces"] = delta
            if delta <= 0:
                log(f"OPIK WARNING: 0 traces exported for this run "
                    f"(before={opik_before}, after={opik_after}) — OTLP export may have failed")
            else:
                log(f"OPIK: {delta} traces exported for this run "
                    f"(before={opik_before}, after={opik_after})")
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try:
                os.remove(_marker_path)
            except OSError:
                pass

    log(f"RUN FINISHED: rc={rc}")
    return rc


# ==================================================================================
# Control utilities (status, stop)
# ==================================================================================
def cmd_status(label: str) -> int:
    evidence_dir, _ = label_paths(label)
    marker = os.path.join(evidence_dir, ".running")
    summary = os.path.join(evidence_dir, "summary.json")

    if os.path.exists(marker):
        try:
            parts = open(marker, encoding="utf-8").read().split()
            start_ts = int(parts[0]) if len(parts) >= 1 else int(time.time())
            pid = int(parts[1]) if len(parts) >= 2 else 0

            alive = _pid_alive(pid) if pid > 0 else False
            state = "running" if alive else "dead"
            print(json.dumps({
                "state": state,
                "pid": pid,
                "elapsed_s": int(time.time()) - start_ts
            }))
        except (ValueError, OSError):
            print(json.dumps({"state": "dead", "error": "corrupted marker"}))
    elif os.path.exists(summary):
        try:
            data = json.load(open(summary, encoding="utf-8"))
            print(json.dumps({
                "state": "done",
                "rc": data.get("rc"),
                "verifier": data.get("verifier"),
                "probe_result": data.get("probe_result"),
                "turns": data.get("turns"),
                "session_id": data.get("session_id"),
                "cache_hit_rate": data.get("cache_hit_rate"),
                "elapsed_s": data.get("elapsed_s"),
                "errors": data.get("errors", [])
            }))
        except Exception as e:
            print(json.dumps({"state": "done", "error": f"summary read error: {e}"}))
    else:
        print(json.dumps({"state": "missing"}))
    return 0


def cmd_stop(label: str) -> int:
    evidence_dir, _ = label_paths(label)
    marker = os.path.join(evidence_dir, ".running")
    if not os.path.exists(marker):
        log(f"Run {label} is not started")
        return 1
    try:
        parts = open(marker, encoding="utf-8").read().split()
        pid = int(parts[1]) if len(parts) >= 2 else 0
    except (ValueError, OSError):
        log(f"Failed to read the PID from the marker {marker}")
        return 1

    if pid > 0:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    log(f"Stop signal sent for {label} (PID {pid})")
    return 0


# ==================================================================================
# Launch orchestration (R2: the former launch.sh + sandbox-run.sh, in Python)
# ==================================================================================
def _inner_run_argv(args) -> list:
    """The container-side / child-side `run` argv (single source)."""
    inner = ["run", args.ticket]
    if args.direct:
        inner.append("--direct")
    if args.local_retries != DEFAULT_RETRIES:
        inner += ["--local-retries", str(args.local_retries)]
    inner += ["--", args.label, *args.extra]
    return inner


def run_sandboxed(args) -> int:
    """Host-side sync run: supervise the Docker container (replaces
    sandbox-run.sh). The marker carries THIS process's pid — cmd_stop's
    killpg lands here, and the try/finally stops the container and removes
    the marker on every exit path (normal return, crash, signal)."""
    evidence_dir, _ = label_paths(args.label)
    os.makedirs(evidence_dir, exist_ok=True)
    # Mount points must exist before `docker run` (else Docker creates them
    # root-owned).
    for d in ("src", "tests", "docs", "scripts", "evidence"):
        os.makedirs(os.path.join(REPO_ROOT, d), exist_ok=True)

    marker = os.path.join(evidence_dir, ".running")
    with open(marker, "w", encoding="utf-8") as f:
        f.write(f"{int(time.time())} {os.getpid()}\n")

    _install_signal_handlers()
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    # The container runs the IMAGE's system python (the SDK is baked in);
    # the host venv python is only for the host-side gates.
    name, argv = sandbox.sandbox_argv(
        REPO_ROOT, LOG_DIR, image,
        ["/usr/bin/python3", "launcher/stanok.py"] + _inner_run_argv(args))
    log(f"SANDBOX: docker container {name}")
    try:
        proc = subprocess.Popen(argv, start_new_session=True)
        rc = proc.wait()
    except KeyboardInterrupt:
        rc = _INTERRUPTED_RC or 130
    finally:
        sandbox.docker_stop(name)
        try:
            os.remove(marker)
        except OSError:
            pass
    return rc


def launch_background(args) -> int:
    """Background run (replaces launch.sh's nohup branch): a detached
    self-spawn executes the sync path — the child writes the marker with its
    own pid and supervises the container (or runs in-process under
    STANOK_NO_SANDBOX). The parent exits 0 immediately."""
    log_path = os.path.join(LOG_DIR, f"{args.label}.launch.log")
    child_argv = [sys.executable, os.path.abspath(__file__)] + _inner_run_argv(args)
    with open(log_path, "a", encoding="utf-8") as lf:
        child = subprocess.Popen(child_argv, stdout=lf, stderr=subprocess.STDOUT,
                                 start_new_session=True, cwd=REPO_ROOT)
    log(f"Machine launched in the background (PID {child.pid}). Log: {log_path}")
    return 0


# ==================================================================================
# CLI entry point
# ==================================================================================
def _resolve_ticket(arg: str, direct: bool = False) -> str:
    if direct:
        candidates = [os.path.join(REPO_ROOT, arg), os.path.abspath(arg)]
    else:
        candidates = [
            os.path.join(os.path.dirname(REPO_ROOT), arg),  # project root (highest priority)
            os.path.join(REPO_ROOT, arg),                    # machine root
            os.path.abspath(arg)                             # as given
        ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[0]


def main() -> int:
    root_refusal()

    p = argparse.ArgumentParser(prog="stanok", description="Stanok 4.2 Runner")
    sub = p.add_subparsers(dest="cmd", required=True)

    # R2: argparse is the single source of the CLI (the former launch.sh flag
    # parsing is gone). `--` separates the label from extra positionals — a
    # label starting with `--` stays positional (the label-guard test relies
    # on it: `run <ticket> -- --background` -> label="--background" -> rc=15).
    r = sub.add_parser("run")
    r.add_argument("ticket")
    r.add_argument("label")
    r.add_argument("extra", nargs="*", default=[])
    r.add_argument("--direct", action="store_true")
    r.add_argument("--local-retries", type=int, default=DEFAULT_RETRIES)
    r.add_argument("--background", action="store_true")

    s = sub.add_parser("status")
    s.add_argument("label")

    st = sub.add_parser("stop")
    st.add_argument("label")

    # Single-source cleanliness gate for launch.sh (host side). Exit 22 on a
    # dirty REPO_ROOT, 0 when clean — no side effects.
    sub.add_parser("check-dirty")

    args = p.parse_args()

    if args.cmd == "check-dirty":
        return 22 if dirty_tree_gate() else 0
    if args.cmd == "status":
        return cmd_status(args.label)
    if args.cmd == "stop":
        return cmd_stop(args.label)

    if args.cmd == "run":
        evidence_dir, _ = label_paths(args.label)
        marker = os.path.join(evidence_dir, ".running")

        def early_abort(rc: int, err_msg: str) -> int:
            log(err_msg)
            if os.path.exists(marker):
                try:
                    os.remove(marker)
                except OSError:
                    pass
            os.makedirs(evidence_dir, exist_ok=True)
            sum_path = os.path.join(evidence_dir, "summary.json")
            if not os.path.exists(sum_path):
                job = {
                    "label": args.label,
                    "ticket": args.ticket,
                    "rc": rc,
                    "verifier": "FAIL",
                    "probe_result": "EARLY-ABORT",
                    "turns": 0,
                    "error": err_msg,
                }
                with open(sum_path, "w", encoding="utf-8") as f:
                    json.dump(build_summary(job, 0), f, ensure_ascii=False, indent=2)
            return rc

        if validate_label(args.label):
            return early_abort(15, f"ERROR: Invalid label {args.label}")

        # ROLE-LEAK (rc=24): a parent CLAUDE.md above the repo would be auto-loaded
        # into the machine session (cwd = REPO_ROOT) -> role leak. Fail-closed before
        # reset/lock/preflight, no side effects.
        parent_claude = os.path.join(os.path.dirname(REPO_ROOT), "CLAUDE.md")
        if os.path.isfile(parent_claude):
            return early_abort(24, f"ERROR: ROLE-LEAK: parent CLAUDE.md above the repo: {parent_claude}")

        args.ticket_path = _resolve_ticket(args.ticket, direct=args.direct)
        if not os.path.isfile(args.ticket_path):
            return early_abort(13, f"ERROR: Ticket not found: {args.ticket_path}")

        if dirty_tree_gate():
            return early_abort(22, "ERROR: the machine repo contains uncommitted changes (rc=22)")

        # R2: launch orchestration (the former launch.sh branches, in Python).
        in_container = os.environ.get("STANOK_IN_CONTAINER") == "1"
        no_sandbox = os.environ.get("STANOK_NO_SANDBOX") == "1"

        if args.background:
            # The child re-runs these gates and takes the lock itself; the
            # parent must not hold the lock (flock would deadlock the child).
            return launch_background(args)

        if in_container or no_sandbox:
            # In-process session (container-side Runner, or host no-sandbox):
            # the lock serializes runs of this repo.
            lock_path = os.path.join(LOG_DIR, f"stanok-{hashlib.md5(REPO_ROOT.encode()).hexdigest()[:12]}.lock")
            lf = open(lock_path, "w")
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return early_abort(21, f"LOCK: the repo is already busy with another run ({lock_path})")
            return cmd_run(args)

        # Host sync: supervise the Docker container (launcher/sandbox.py).
        # The container-side Runner re-runs the gates and takes the lock.
        if shutil.which("docker") is None:
            return early_abort(1, "ERROR: docker not found on PATH")
        return run_sandboxed(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
