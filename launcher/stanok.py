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

# --- Circuit constants -------------------------------------------------------------
LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
# If STANOK_REPO is not set, we go up one level (stanok/launcher -> stanok)
DEFAULT_REPO = os.path.abspath(os.path.join(LAUNCHER_DIR, ".."))
REPO_ROOT = os.path.abspath(os.environ.get("STANOK_REPO", DEFAULT_REPO))
LOG_DIR = os.environ.get("STANOK_LOG_DIR", "/tmp/stanok-logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOCAL_MODEL = os.environ.get("STANOK_MODEL", "Qwen3.8-27B-MTP")
SERVER_URL = os.environ.get("STANOK_SERVER_URL", "http://127.0.0.1:8080")
CLAUDE_BIN = os.environ.get("STANOK_CLAUDE_BIN", shutil.which("claude") or "claude")

MAX_TEST_LINES = 60
MAX_TEST_BYTES = 4096
DEFAULT_RETRIES = int(os.environ.get("STANOK_LOCAL_RETRIES", "2"))

API_TIMEOUT_S = max(1.0, float(os.environ.get("STANOK_API_TIMEOUT_S", "600")))
TURN_TIMEOUT_S = float(os.environ.get("STANOK_TURN_TIMEOUT_S", "1200"))

if TURN_TIMEOUT_S <= API_TIMEOUT_S:
    TURN_TIMEOUT_S = API_TIMEOUT_S + max(15.0, API_TIMEOUT_S * 0.2)

API_TIMEOUT_MS = str(int(API_TIMEOUT_S * 1000))
CURATED_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]

_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

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
    try:
        out = subprocess.run(["git", "status", "--porcelain"],
                             cwd=REPO_ROOT, capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return True
    except OSError:
        pass
    return False


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
    window = _required_context_window() or 125000
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


def prepare_workspace() -> int:
    # SEC-01: .git is read-only inside the bwrap sandbox — NO git writes here.
    # The cleanliness gate is dirty_tree_gate() (single source, called by main()
    # rc=22 and by launch.sh via `check-dirty`). This function only prepares the
    # writable workspace.
    try:
        for d in ("src", "tests", "docs"):
            os.makedirs(os.path.join(REPO_ROOT, d), exist_ok=True)
        # D2: the previous run may have frozen test files (chmod a-w, set by
        # hooks/verifier.sh on RED). Unfreeze before this run's test-writing
        # phase — the freeze is per-run, not permanent.
        subprocess.run(["chmod", "-R", "u+w", os.path.join(REPO_ROOT, "tests")],
                       capture_output=True)
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
        if "node:internal/" not in line and "node_modules/" not in line
    ]
    if not cleaned_lines:
        cleaned_lines = raw_text.strip().splitlines()

    if len(cleaned_lines) <= MAX_TEST_LINES:
        res = "\n".join(cleaned_lines)
    else:
        high_pri = re.compile(r"(assertionerror|strictequal|deepstrictequal|expected|actual|not ok\s+\d+|#\s+fail\s+\d+|diff:)", re.I)
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
            res = "\n".join(cleaned_lines[:15] + [f"\n... [lines skipped: {len(cleaned_lines) - MAX_TEST_LINES}] ...\n"] + cleaned_lines[-45:])

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


def verify_gate() -> tuple[bool, list[tuple[str, str]]]:
    """Verdict = run every test the project's runner declares (D3).

    Discovery goes through the project entrypoint too (run.sh list), so the
    machine no longer hardcodes the *.test.js convention.
    """
    try:
        lp = subprocess.run(["bash", "scripts/run.sh", "list"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return (False, [("(no tests)", f"run.sh list failed: {e}")])
    tests = [ln.strip() for ln in (lp.stdout or "").splitlines() if ln.strip()]
    if not tests:
        return (False, [("(no tests)", "The project runner declares no tests")])

    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=min(8, len(tests))) as ex:
        futures = {ex.submit(_run_one_test, t): t for t in tests}
        for fut in as_completed(futures):
            res = fut.result()
            if res is not None:
                failures.append(res)
    failures.sort(key=lambda x: x[0])
    return (len(failures) == 0, failures)


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


async def _execute_turn(client, prompt: str, turn: int, stream_f, job: dict, local_run_id: str) -> tuple[dict, dict]:
    """Returns (turn_total, live_window).

    turn_total  — ResultMessage.usage: cumulative across the turn's API calls
                  (for session totals).
    live_window — the last AssistantMessage.usage: the prompt size actually sent
                  on the final API call (the true context window, for CONTEXT-ROT).
    """
    await client.query(prompt)
    live_window = {}
    turn_total = {}
    async for msg in client.receive_response():
        sid = getattr(msg, "session_id", None)
        if not sid and hasattr(msg, "data") and isinstance(msg.data, dict):
            sid = msg.data.get("session_id")
        if sid and not job.get("session_id"):
            job["session_id"] = str(sid)

        u = _extract_usage(msg)
        if u:
            if type(msg).__name__ == "ResultMessage":
                turn_total = u
            else:
                live_window = u

        _write_stream_msg(stream_f, turn, msg)
    return (turn_total or live_window), live_window


async def run_continuous_session(job: dict, ticket_prompt: str, max_retries: int) -> int:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    local_run_id = str(uuid.uuid4())[:8]
    stream_out_path = os.path.join(_live_dir, f"session-{local_run_id}.jsonl")

    options = ClaudeAgentOptions(
        cli_path=CLAUDE_BIN,
        cwd=REPO_ROOT,
        setting_sources=["project"],
        settings=f"{REPO_ROOT}/.claude/settings.stanok.json",
        permission_mode="default",
        allowed_tools=CURATED_TOOLS,
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

    with open(stream_out_path, "a", encoding="utf-8") as stream_f:
        async with ClaudeSDKClient(options=options) as client:
            for turn in range(1, max_turns + 1):
                log(f"\n>>> Turn {turn}/{max_turns} {'(Fixing errors in src/)' if turn > 1 else '(Ticket start)'} <<<")

                t0 = time.time()
                turn_task = asyncio.create_task(
                    _execute_turn(client, current_prompt, turn, stream_f, job, local_run_id)
                )

                try:
                    turn_usage, live_window = await asyncio.wait_for(asyncio.shield(turn_task), timeout=TURN_TIMEOUT_S)
                except asyncio.TimeoutError:
                    log(f"TIMEOUT: turn {turn} exceeded {TURN_TIMEOUT_S:.0f}s (silent stall) -> interrupt")
                    try:
                        await client.interrupt()
                    except Exception as e:
                        log(f"WARN: client.interrupt() finished with an error: {e}")

                    try:
                        await asyncio.wait_for(turn_task, timeout=5.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass

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
                })

                rot_threshold = context_rot_threshold()
                if live_context > rot_threshold:
                    log(f"  [CONTEXT-ROT WARN] Live context window ({live_context} tokens) "
                        f"exceeded the threshold {rot_threshold}. Model attention may degrade.")

                verify_ok, failures = verify_gate()

                if verify_ok:
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
                            "1. There are no test files in the tests/ directory! Create the reference *.test.js strictly per the ticket specification.\n"
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


def write_summary(job: dict, elapsed_s: int) -> None:
    """Builds the exact summary.json contract expected by the L1 Supervisor."""
    turns = job.get("turns", 1)
    verifier = job.get("verifier", "FAIL")
    rc = job.get("rc", 1)

    if rc == 0 and verifier == "PASS":
        probe_result = "CLEAN-FIRST" if turns == 1 else "PASS-AFTER-LOCAL-RETRY"
        c5 = "PASS"
    else:
        probe_result = "VERIFY-FAIL" if rc != 0 else "PASS"
        c5 = "PASS" if rc == 0 else "FAIL"

    if job.get("probe_result"):
        probe_result = job["probe_result"]

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

    summary = {
        "label": job.get("label"),
        "ticket": job.get("ticket"),
        "rc": rc,
        "verifier": verifier,
        "probe_result": probe_result,
        "review_verdict": "CLEAN" if rc == 0 else "DEFECT",
        "cloud_calls": 0,
        "c5": c5,
        "turns": turns,
        "elapsed_s": elapsed_s,
        "session_id": job.get("session_id"),
        "tokens": job.get("tokens", {}),
        "cache_hit_rate": job.get("cache_hit_rate", "0.0%"),
        "inference_telemetry": inference_telemetry,
        "errors": [job["error"]] if job.get("error") else [],
        "failures": job.get("failures", []),
    }
    with open(os.path.join(_evidence_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


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

    # Preserve the host PID if it was already set by launch.sh
    if os.path.exists(_marker_path):
        try:
            parts = open(_marker_path, "r", encoding="utf-8").read().split()
            if len(parts) >= 2:
                start_ts = int(parts[0])
                recorded_pid = int(parts[1])
        except (ValueError, OSError):
            pass
    elif os.environ.get("STANOK_HOST_PID"):
        try:
            recorded_pid = int(os.environ["STANOK_HOST_PID"])
        except ValueError:
            pass

    with open(_marker_path, "w", encoding="utf-8") as f:
        f.write(f"{start_ts} {recorded_pid}\n")

    _install_signal_handlers()

    job = {"label": args.label, "ticket": args.ticket}
    log(f"STANOK 4.2 RUNNER | Repo: {REPO_ROOT} | Label: {args.label}")
    if args.direct:
        log("--direct MODE: the ticket path is resolved relative to the repository")

    if not preflight_server():
        job["rc"] = 20
        job["error"] = f"Server unavailable ({SERVER_URL})"
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 20

    if prepare_workspace() != 0:
        job["rc"] = 14
        job["error"] = "workspace prep error"
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 14

    rc = 1
    try:
        with open(args.ticket_path, encoding="utf-8") as f:
            ticket_prompt = f.read().strip()
        rc = asyncio.run(run_continuous_session(job, ticket_prompt, args.local_retries))
    except KeyboardInterrupt:
        rc = _INTERRUPTED_RC or 130
    except Exception as e:
        log(f"FATAL EXCEPTION: {e}")
        job["error"] = str(e)
        rc = 1
    finally:
        job["rc"] = rc
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

    r = sub.add_parser("run")
    r.add_argument("ticket")
    r.add_argument("label")
    r.add_argument("--direct", action="store_true")
    r.add_argument("--local-retries", type=int, default=DEFAULT_RETRIES)

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
                payload = {
                    "label": args.label,
                    "ticket": args.ticket,
                    "rc": rc,
                    "verifier": "FAIL",
                    "probe_result": "EARLY-ABORT",
                    "review_verdict": "DEFECT",
                    "cloud_calls": 0,
                    "c5": "FAIL",
                    "turns": 0,
                    "elapsed_s": 0,
                    "session_id": None,
                    "tokens": {},
                    "cache_hit_rate": "0.0%",
                    "errors": [err_msg],
                    "failures": [],
                }
                with open(sum_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
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

        # Background mode is owned by launch.sh (host-side nohup): inside the bwrap
        # namespace a self-re-spawn would bypass the lock and the host gates.
        lock_path = os.path.join(LOG_DIR, f"stanok-{hashlib.md5(REPO_ROOT.encode()).hexdigest()[:12]}.lock")
        lf = open(lock_path, "w")
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return early_abort(21, f"LOCK: the repo is already busy with another run ({lock_path})")

        return cmd_run(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
