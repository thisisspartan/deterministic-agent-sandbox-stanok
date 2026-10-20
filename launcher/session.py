"""session — the continuous Claude session: turns, watchdog, verifier hook, loop-trap.

build_agent_env, _execute_turn (returns TurnResult), _post_turn_decision (the
post-turn verdict pipeline), _verifier_hook (R1), run_continuous_session,
the CC-207 circuit breaker and the signal handlers. Static config arrives as
the passed-in Config; per-run mutable state (live_dir, marker_path,
interrupted_rc) as the passed-in RunState (C). _HOOK_TEST_TIMEOUT_S is a
module global — tests_harness patches `session._HOOK_TEST_TIMEOUT_S`.
"""

import asyncio
import dataclasses
import functools
import json
import os
import re
import signal
import subprocess
import time
import uuid
from launcher.exitcodes import ExitCode
from launcher.logs import log
from launcher.gates import context_rot_threshold
from launcher.verify import _check_contract_lock, _contract_lock_forced_fail, _fix_prompt_rules, _tests_manifest, verify_gate


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


# ==================================================================================
# Loop-trap circuit breaker (CC-207)
# ==================================================================================
def _loop_trap_path(run_state) -> str:
    """CC-207: single source of the marker path. The hook writes it (via the
    STANOK_LOOP_TRAP_FILE env handed to the machine process), the launcher
    reads it. live_dir (LOG_DIR/<label>) is the rw log dir in the container
    (the Pod's LOG_DIR mount) — the channel needs no new mount."""
    return os.path.join(run_state.live_dir, "loop-trap.json")


def _read_loop_trap(marker_path: str) -> dict | None:
    """Best-effort read of the loop-guard termination marker: missing /
    unreadable / non-JSON / directory -> None. A broken marker must never
    kill the turn — the hook's fail-open invariant, mirrored on the reader."""
    try:
        with open(marker_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _loop_trap_verdict(job: dict, loop_trap: dict) -> int:
    """CC-207: the circuit-breaker verdict on a job dict (the
    _contract_lock_forced_fail pattern). No fix prompt, no local retries: a
    retry re-enters the same loop — the marker is cumulative for the
    session. rc=1 is the existing defect code (no new rc)."""
    job["probe_result"] = "LOOP-TRAP"
    job["loop_trap"] = loop_trap
    job["verifier"] = "FAIL"
    job["error"] = (
        f"LOOP-TRAP: {loop_trap.get('tool')} repeated {loop_trap.get('n')}x "
        "consecutively — session terminated by the circuit breaker"
    )
    log("LOOP-TRAP: fail-closed (no fix prompt, no retry — the marker is cumulative)")
    return 1


# ==================================================================================
# Inference environment (Prefix Invariance)
# ==================================================================================
def build_agent_env(cfg, run_state) -> dict[str, str]:
    """Runtime-only env for the machine process.

    Static machine config lives in `.claude/settings.stanok.json` -> `env`, which
    claude applies natively at startup via `Object.assign(process.env,
    settings.env)` (cli.js `jUK()`). That assignment runs AFTER the SDK has set
    this dict, so any key present in BOTH would silently win from settings and
    kill the runtime knob. Hence: only derive-from-runtime keys belong here
    (endpoint, model, timeout); everything static belongs in settings.

    No proxy: the machine has no web tools (cfg.curated_tools) and its only
    outbound is the local API server, which is directly reachable (the Pod's
    egress boundary is the NetworkPolicy, not a proxy).
    """
    agent_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "ANTHROPIC_BASE_URL": cfg.server_url,
        "ANTHROPIC_MODEL": cfg.model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": cfg.model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": cfg.model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": cfg.model,
        "CLAUDE_CODE_SUBAGENT_MODEL": cfg.model,
        "API_TIMEOUT_MS": cfg.api_timeout_ms,
        # CC-207: the loop-guard termination-marker channel. The hook writes
        # it at the 5th consecutive identical call; _execute_turn reads it
        # mid-turn. Derived-from-runtime (per-run dir) -> belongs here.
        "STANOK_LOOP_TRAP_FILE": _loop_trap_path(run_state),
        # CC-236 (incident cc235, operator trace review 2026-10-11): the CLI
        # does NOT export CLAUDE_PROJECT_DIR for hooks (cli.js 2.1.88 exports
        # it only in plugin context). The PreToolUse command registered in
        # .claude/settings.json references $CLAUDE_PROJECT_DIR; unset it
        # expands to /.claude/hooks/... -> exit 127 on every tool call
        # (num_non_blocking_error=1) -> the loop guard is dead. Derived-from-
        # runtime (cfg.repo_root: host checkout vs /stanok-work/repo in the
        # Pod) -> belongs here, not in settings.
        "CLAUDE_PROJECT_DIR": cfg.repo_root,
    }
    # PLAN-HYGIENE 2026-10-08: no hardcoded AUTO_COMPACT default (the old
    # "128000" silently overrode the settings window when the env was unset).
    # Pass the key through ONLY when the operator exported it (P0-launch.sh
    # derives it from settings); otherwise omit it — settings.env applies.
    acw = os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    if acw:
        agent_env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = acw
    return agent_env


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


# ==================================================================================
# CC-247: the test-fit proxy metric (operator trace review of cc246).
# Count test-file edits that happen AFTER the first GREEN run of
# `scripts/run.sh test` observed in the agent's own Bash stream. Proxy only:
# typed counters in summary.json, no gate, no text. The anchor is the agent's
# Bash output — the in-process hook-green was rejected on the trace: the
# PostToolUse hook fires AFTER the edit it would need to anchor (its first
# green in cc246 lands on the tie Edit itself, so it can never count it).
# Documented skips: greens whose last shell segment is not run.sh and that
# carry no rc echo (`run.sh test --all | tail`); greens observed only by the
# in-process verifier hook (silent on rc=0); greens observed only by the host
# verify_gate (runs after the turn ends).
# ==================================================================================
_RUN_SH_TEST_RE = re.compile(r"\brun\.sh\s+test\b")
_SHELL_SEGMENT_RE = re.compile(r"[;&|\n]+")


def _shell_last_segment(command: str) -> str:
    """The last shell segment of a command line (split on ; | && || and
    newlines). If it is the run.sh test call, the exit code the CLI reports
    IS run.sh's rc."""
    segments = [s for s in _SHELL_SEGMENT_RE.split(command) if s.strip()]
    return segments[-1].strip() if segments else ""


def _bash_test_green(command, is_error: bool, result_text: str) -> bool:
    """CC-247 anchor: did this Bash call run `run.sh test` GREEN?

    1. the command must invoke `run.sh test`;
    2. if the LAST shell segment is the run.sh test call, the exit code the
       CLI reports IS run.sh's rc -> green iff is_error is False;
    3. masked forms (`; echo "rc=$?"` — the cc246 idiom, which masks the
       exit code) are trusted only via an explicit `rc=0` in the output."""
    if not isinstance(command, str) or not _RUN_SH_TEST_RE.search(command):
        return False
    if _RUN_SH_TEST_RE.search(_shell_last_segment(command)):
        return not is_error
    if "rc=$?" in command and re.search(r"\brc=0\b", result_text or ""):
        return True
    return False


def _test_write_kind(cfg, tool_name: str, tool_input) -> "str | None":
    """Classify a Write/Edit tool_use against the tests/ tree:
    "edit" — the target file EXISTS (editing an already-green test: the
    test-fitting signal; a Write over an existing file is an edit too);
    "new"  — a Write creating a NEW file under tests/ (normal TDD growth);
    None   — not a tests/ write (src/, docs/, no path) or an Edit to a
    file that does not exist (it edits nothing)."""
    if tool_name not in ("Write", "Edit") or not isinstance(tool_input, dict):
        return None
    fp = tool_input.get("file_path")
    if not fp or not isinstance(fp, str):
        return None
    if not fp.startswith("/"):
        fp = os.path.join(cfg.repo_root, fp)
    abs_path = os.path.realpath(fp)
    tests_dir = os.path.join(cfg.repo_root, "tests")
    if not abs_path.startswith(tests_dir + os.sep):
        return None
    if os.path.isfile(abs_path):
        return "edit"
    if tool_name == "Write":
        return "new"
    return None


def _tool_result_text(block) -> str:
    """The text of a ToolResultBlock: str content, or a list of
    str / {"type":"text","text":...} / TextBlock items."""
    content = getattr(block, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                t = getattr(item, "text", None)
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts)
    return ""


@dataclasses.dataclass
class TurnResult:
    """The typed outcome of one agent turn (what _execute_turn returns).

    usage       — ResultMessage.usage: cumulative across the turn's API calls
                  (for session totals).
    live_window — the last AssistantMessage.usage: the prompt size actually sent
                  on the final API call (the true context window, for CONTEXT-ROT).
    writes      — count of Write/Edit tool_use blocks in the turn (NO-OP assert,
                  W2.4; immune to test side effects, unlike a file manifest).
    error       — "" on a clean turn; otherwise the API/max-turns error string
                  (CLI_MAX_TURNS_EXCEEDED or the ResultMessage error detail).
    loop_trap   — CC-207: the loop-guard termination marker read mid-turn
                  (the hook denied the 5th consecutive identical call), or
                  None if the breaker did not trip.
    bash_total  — CC-234: count of Bash tool_use blocks in the turn.
    bash_ok     — CC-234: count of their tool_results that came back without
                  is_error (the agent's own tooling worked; bash_ok==0 with a
                  verifier PASS = the agent wrote blind — PASS-BLIND).
    test_edits_after_green / test_new_tests_after_green — CC-247: the
                  test-fit counters of this turn (edits of an EXISTING file
                  under tests/ after the first observed green / new test
                  files created after it; the green flag lives in
                  job["_green_seen"], session-scoped).
    compactions   — P1 telemetry (Opik analysis CC-302/CC-304, 2026-10-20):
                  the native compact_boundary events observed in this turn
                  (see _compaction_entry); [{"trigger": str, "pre_tokens": int}].
    """

    usage: dict
    live_window: dict
    writes: int
    error: str
    loop_trap: dict | None
    bash_total: int = 0
    bash_ok: int = 0
    test_edits_after_green: int = 0
    test_new_tests_after_green: int = 0
    compactions: list = dataclasses.field(default_factory=list)


def _compaction_entry(msg) -> dict | None:
    """P1 telemetry (Opik analysis CC-302/CC-304, 2026-10-20): the pinned CLI
    (cli.js 2.1.88) emits a native stream event on every autocompact —
    {"type":"system","subtype":"compact_boundary","compact_metadata":
    {"trigger": ..., "pre_tokens": ...}}; the Agent SDK passes unknown system
    subtypes through as a generic SystemMessage carrying the raw dict in
    .data. Before this field a compaction was invisible in summary.json: the
    token totals EXCLUDE compaction calls exactly (cc304: 80,837-6,200 =
    the published 74,637) but nothing recorded that 83 s of summarisation
    happened. This records the event; it changes no totals.

    Returns the typed pair {"trigger": str, "pre_tokens": int} for a
    well-formed compact_boundary, None for any other message or a malformed
    payload (never a fabricated 0: no event, no entry)."""
    if getattr(msg, "subtype", None) != "compact_boundary":
        return None
    data = getattr(msg, "data", None)
    cm = data.get("compact_metadata") if isinstance(data, dict) else None
    if not isinstance(cm, dict):
        return None
    trigger = cm.get("trigger")
    pre_tokens = cm.get("pre_tokens")
    if not isinstance(trigger, str):
        trigger = ""
    if not isinstance(pre_tokens, int) or isinstance(pre_tokens, bool):
        return None
    return {"trigger": trigger, "pre_tokens": pre_tokens}


async def _execute_turn(client, prompt: str, turn: int, stream_f, job: dict,
                       run_state, cfg) -> TurnResult:
    """Run one turn on the live client; return its TurnResult."""
    from claude_agent_sdk import ResultMessage

    await client.query(prompt)
    live_window = {}
    turn_total = {}
    writes = 0
    turn_error = ""
    loop_trap = None
    bash_total = 0
    bash_ok = 0
    bash_ids = set()
    compactions = []
    # CC-247: run.sh-test Bash calls awaiting their tool_result (id -> command)
    test_bash_cmds = {}
    test_edits_after_green = 0
    test_new_tests_after_green = 0
    marker_path = _loop_trap_path(run_state)
    async for msg in client.receive_response():
        sid = getattr(msg, "session_id", None)
        if not sid and hasattr(msg, "data") and isinstance(msg.data, dict):
            sid = msg.data.get("session_id")
        if sid and not job.get("session_id"):
            job["session_id"] = str(sid)

        compaction = _compaction_entry(msg)
        if compaction is not None:
            compactions.append(compaction)

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
            subtype = getattr(msg, "subtype", None)
            errors = getattr(msg, "errors", None)
            terminal_reason = getattr(msg, "terminal_reason", None)
            if is_err:
                if subtype == "error_max_turns" or terminal_reason == "max_turns":
                    turn_error = "CLI_MAX_TURNS_EXCEEDED: agent reached max-turns ceiling"
                else:
                    detail = res
                    if not detail and isinstance(errors, list) and errors:
                        detail = "; ".join(str(e) for e in errors)
                    turn_error = str(detail or f"unknown API error (subtype={subtype})")

        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                name = getattr(block, "name", None)
                if name in ("Write", "Edit"):
                    writes += 1
                    # CC-247: after the first observed green, a write to an
                    # EXISTING tests/ file is the test-fitting signal; a new
                    # tests/ file is normal TDD growth (counted separately).
                    if job.get("_green_seen"):
                        kind = _test_write_kind(cfg, name, getattr(block, "input", None))
                        if kind == "edit":
                            test_edits_after_green += 1
                        elif kind == "new":
                            test_new_tests_after_green += 1
                elif name == "Bash":
                    # CC-234: the agent's own tooling — count calls and their
                    # results (ToolResultBlock carries tool_use_id/is_error).
                    bash_total += 1
                    tid = getattr(block, "id", None)
                    if tid is not None:
                        bash_ids.add(tid)
                        # CC-247: remember run.sh-test commands; their result
                        # is the green anchor.
                        tool_input = getattr(block, "input", None)
                        cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
                        if isinstance(cmd, str) and _RUN_SH_TEST_RE.search(cmd):
                            test_bash_cmds[tid] = cmd
                else:
                    tid = getattr(block, "tool_use_id", None)
                    if tid is not None and tid in bash_ids:
                        bash_ids.discard(tid)  # count each result once
                        if not getattr(block, "is_error", False):
                            bash_ok += 1
                    if tid is not None and tid in test_bash_cmds:
                        # CC-247 anchor: the first green sets the session flag.
                        cmd = test_bash_cmds.pop(tid)
                        if _bash_test_green(cmd, getattr(block, "is_error", False),
                                           _tool_result_text(block)):
                            job["_green_seen"] = True

        _write_stream_msg(stream_f, turn, msg)

        # CC-207: mid-turn breaker check — CC-204-retry3 burned the whole
        # 1584 s turn before any turn-end check could fire. One stat per
        # message, no polling loop; a broken marker is not fatal (retried
        # on the next message).
        if loop_trap is None and os.path.exists(marker_path):
            loop_trap = _read_loop_trap(marker_path)
            if loop_trap is not None:
                break
    return TurnResult(
        usage=turn_total or live_window,
        live_window=live_window,
        writes=writes,
        error=turn_error,
        loop_trap=loop_trap,
        bash_total=bash_total,
        bash_ok=bash_ok,
        test_edits_after_green=test_edits_after_green,
        test_new_tests_after_green=test_new_tests_after_green,
        compactions=compactions,
    )


# contract_lock (T5, CC-137): the PreToolUse deny hook is GONE. Its job — a
# pre-existing protected file cannot be rewritten — is now done by the MOUNT
# (T4b/CC-136: the protected files are bound :ro over the rw carve-out, so the
# write is an EROFS refusal from the kernel, not a Python decision), with the
# post-turn SHA256 manifest diff (_check_contract_lock) as the independent
# second echelon that catches anything the filesystem cannot (a DELETED test
# file is a write to its directory) and fails the run closed.
#
# The hook was deleted only after that e2e existed: a declared ABSENT path is
# carved out through its parent dir, so before CC-136 the mount layer alone
# left the pre-existing tests writable (see tickets/TASK-STANOK-CC-135.md
# §Non-goals and CC-136).


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


def _resolve_hook_target(cfg, hook_input: dict) -> "str | None":
    """Resolve a PostToolUse hook_input to a repo-relative tests/ test path,
    or None when this tool call is not a test-file write we must verify.

    Filters (each was an early `return {}` in the original hook): no
    file_path; path outside tests/; not an existing file; no scripts/run.sh
    to run the test with."""
    tool_input = hook_input.get("tool_input") or {}
    fp = tool_input.get("file_path")
    if not fp:
        return None
    if not fp.startswith("/"):
        fp = os.path.join(cfg.repo_root, fp)
    abs_path = os.path.realpath(fp)
    tests_dir = os.path.join(cfg.repo_root, "tests")
    if not abs_path.startswith(tests_dir + os.sep):
        return None
    if not os.path.isfile(abs_path):
        return None
    if not os.path.isfile(os.path.join(cfg.repo_root, "scripts", "run.sh")):
        return None
    return os.path.relpath(abs_path, cfg.repo_root)


async def _run_hook_test(cfg, rel: str) -> tuple[int, bytes]:
    """Run `scripts/run.sh test <rel>` under the hook backstop timeout.

    Returns (rc, output). rc=124 on timeout (the hook's own backstop).
    Read into a shared list: a cancelled wait_for discards the read task's
    LOCAL state (a communicate() that was cancelled had already consumed the
    pre-kill bytes into its own locals — they were lost). Chunks delivered
    before the deadline survive in `chunks` (bug 6: the timeout message must
    show what the test printed before it hung)."""
    run_sh = os.path.join(cfg.repo_root, "scripts", "run.sh")
    proc = await asyncio.create_subprocess_exec(
        "bash", run_sh, "test", rel,
        cwd=cfg.repo_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    chunks: list[bytes] = []

    async def _drain() -> None:
        while True:
            c = await proc.stdout.read(65536)
            if not c:
                break
            chunks.append(c)

    try:
        await asyncio.wait_for(_drain(), timeout=_HOOK_TEST_TIMEOUT_S)
        await proc.wait()  # pipe EOF can arrive before the exit status
        rc = proc.returncode
    except asyncio.TimeoutError:
        proc.kill()
        await _drain()
        rc = 124
    return rc, b"".join(chunks)


def _hook_verdict(rel: str, rc: int, out: bytes) -> dict:
    """Map a hook-test result to the hook output ({} = stay silent).

    rc=0: GREEN (implementation exists) — stay silent.
    rc=2: runner refused the path (not a test in its terms) — not our concern.
    rc=6: ENV-FAIL (runner unavailable in the image) — an environment
          failure, NOT a red test; emitting RED here is what burned a
          whole turn on CC-081 ("fix" the environment from src/).
    rc=124: the test HUNG (run.sh's 60 s runner timeout, or this hook's own
          backstop) — not a red assertion. "Implement src/ to make it GREEN"
          here is a retry-loop DoS: the model iterates on src/, the test
          hangs again, the hook fires again. Name the failure mode (hang)
          and where to look instead."""
    if rc in (0, 2, 6):
        if rc == 6:
            log(f"VERIFIER HOOK: ENV-FAIL ({rel} rc=6) — runner unavailable, no RED")
        return {}
    text = out.decode("utf-8", "replace")
    tail = "\n".join(text.splitlines()[-25:])
    if rc == 124:
        log(f"VERIFIER HOOK: TIMEOUT-ABORT ({rel} rc=124)")
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"VERIFY: TIMEOUT-ABORT ({rel} rc=124). The test hung "
                    f"past the runner timeout — this is NOT a red test; "
                    f"do not iterate on src/ to make it green. Locate and "
                    f"remove the hang (infinite loop / blocking call) in "
                    f"the test or in the implementation.\n{tail}"
                ),
            }
        }
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


async def _verifier_hook(cfg, hook_input: dict, tool_use_id: "str | None", context) -> dict:
    # W8 double-hook diagnosis: log EVERY invocation with its tool_use_id.
    # After a run: grep 'HOOK-CALL' <launcher log> | awk id | sort | uniq -d —
    # duplicate ids = double registration/call; unique ids = the second
    # callback is internal. Keep this log until the verdict is in CONTEXT.md.
    _ti = hook_input.get("tool_input") or {}
    log(f"HOOK-CALL id={tool_use_id} file={_ti.get('file_path')}")
    try:
        rel = _resolve_hook_target(cfg, hook_input)
        if rel is None:
            return {}
        rc, out = await _run_hook_test(cfg, rel)
        return _hook_verdict(rel, rc, out)
    except Exception as e:
        log(f"VERIFIER HOOK: no-op (error: {e})")
        return {}


def _observability_warnings(job: dict, turn: int, inp: int, live_context: int) -> None:
    """PREFIX-BREAK + CONTEXT-ROT warnings (diagnostics only — never a verdict).

    PREFIX-BREAK: a KV-prefix break shows up exactly as a spike in the turn's
    input_tokens (uncached re-send). Only meaningful from turn 2: on turn 1
    there is no previous turn to break the prefix from, so comparing the first
    prompt against a constant baseline fired a false WARN on every run (CC-126).
    """
    prev_inputs = [t["input_tokens"] for t in job["turn_telemetry"][:-1]]
    if prev_inputs:
        median_prev = sorted(prev_inputs)[len(prev_inputs) // 2]
        if inp > 2 * median_prev:
            job["turn_telemetry"][-1]["prefix_break"] = True
            log(f"  [PREFIX-BREAK WARN] turn {turn} input_tokens={inp} "
                f"> 2x median of previous turns ({median_prev}) — KV prefix likely not reused")

    rot_threshold = context_rot_threshold()
    if rot_threshold is not None and live_context > rot_threshold:
        log(f"  [CONTEXT-ROT WARN] Live context window ({live_context} tokens) "
            f"exceeded the threshold {rot_threshold}. Model attention may degrade.")


def _fix_prompt(failures, turn: int) -> str:
    """The FAIL fix prompt: <verification_result> XML with the failure blocks
    and the <contract_lock> rules the machine must respect while fixing."""
    rules = _fix_prompt_rules(failures)
    fail_xml_blocks = "\n".join([
        f'  <failure test="{name}">\n{diff}\n  </failure>'
        for name, diff in failures
    ])
    return (
        f"<verification_result status=\"FAIL\" turn=\"{turn}\">\n"
        f"<test_errors count=\"{len(failures)}\">\n"
        f"{fail_xml_blocks}\n"
        f"</test_errors>\n"
        f"<contract_lock>\n"
        f"{rules}\n"
        f"</contract_lock>\n"
        f"</verification_result>"
    )


def _post_turn_decision(cfg, job: dict, turn: int, max_turns: int, plan: "SessionPlan",
                       result: TurnResult, tests_manifest_before: dict,
                       inp: int, live_context: int) -> tuple[int | None, str]:
    """Decide what happens after a completed turn (the verdict pipeline).

    Returns (rc, next_prompt): rc is not None -> the run ends with that exit
    code; rc is None -> continue the loop with next_prompt ("" on retry
    exhaustion). The order below is the verdict contract (do not reorder):
    dead-session stop -> contract_lock diff (protected files)
    -> observability warnings -> contract_lock forced FAIL -> verify_gate ->
    ENV-FAIL stop -> NO-OP/PASS verdict -> FAIL fix prompt.
    """
    # A turn that ended with an SDK API error (e.g. "API Error: terminated" —
    # the model server dropped the connection) leaves the session dead:
    # subsequent fix prompts return a stale 0-token result instantly and waste
    # the remaining turns. Stop the run now with a clear error; the supervisor
    # relaunches.
    if result.error:
        log(f"TURN {turn} ended with API error: {result.error!r} — "
            f"session dead, stopping (no fix prompt)")
        job["error"] = f"TURN-{turn} API ERROR: {result.error}"
        job["verifier"] = "FAIL"
        job["turns"] = turn
        return 1, ""

    # contract_lock (W2.5 + P2): did the turn touch pre-existing
    # tests/ or scripts/run.sh?
    _check_contract_lock(cfg, tests_manifest_before, job, turn, plan)

    _observability_warnings(job, turn, inp, live_context)

    # Fail-closed on contract_lock (W2.5 + P2): a tampered tree is decided
    # BEFORE the suite runs — the tests must not execute on a tree already
    # declared tampered (operator review 2026-10-09; the old placement after
    # verify_gate only overwrote the verdict after burning the suite).
    forced = _contract_lock_forced_fail(job, turn)
    if forced is not None:
        return forced, ""

    verify_ok, failures, env_fail = verify_gate(cfg, plan)

    if env_fail:
        # ENV-FAIL (run.sh rc=6): the test runner is unavailable
        # in the image — an environment defect, not a code
        # defect. The model cannot fix the image from src/; a
        # fix prompt here is what burned turn 2 on CC-081. Stop
        # fail-closed before the next turn (run-level rc=16).
        log("ENV-FAIL: test runner unavailable (run.sh rc=6) — "
            "no fix prompt, stopping (fail-closed)")
        job["verifier"] = "FAIL"
        job["error"] = "ENV-FAIL: test runner unavailable (run.sh rc=6)"
        job["failures"] = failures
        job["turns"] = turn
        return int(ExitCode.ENV_FAIL), ""

    if verify_ok:
        # NO-OP assert (W2.4): a turn-1 pass with zero Write/Edit
        # tool_use means the machine did no work — the artifacts
        # pre-existed. rc=1 (defect); no new rc code is introduced.
        if turn == 1 and result.writes == 0:
            log("NO-OP-PASS: verifier passed on turn 1 with zero "
                "Write/Edit calls — the machine did no work")
            job["verifier"] = "PASS"
            job["probe_result"] = "NO-OP-PASS"
            job["turns"] = turn
            return 1, ""
        # CC-234 (operator spec 2026-10-11): a PASS where the agent never
        # completed a single successful Bash call is NOT a clean acceptance —
        # the in-process verifier hook can green the suite while the agent's
        # own Bash is dead (the cc231/cc233 incident: every call died on the
        # read-only /tmp, the agent wrote blind). rc/verifier stay as
        # measured; probe_result records the demotion (decide() override).
        activity = job.get("tool_activity") or {}
        if activity.get("bash_ok", 0) == 0:
            log("PASS-BLIND: verifier PASS but zero successful Bash calls "
                "by the agent — not a clean acceptance")
            job["probe_result"] = "PASS-BLIND"
        log("VERIFIER: PASS — All tests passed successfully!")
        job["verifier"] = "PASS"
        job["turns"] = turn
        return 0, ""

    log(f"VERIFIER: FAIL — Failed tests: {len(failures)}")
    job["failures"] = failures

    if turn < max_turns:
        return None, _fix_prompt(failures, turn)

    log("Retry limit exhausted (Context Inertia Guard). Finishing.")
    return None, ""


def _agent_options(cfg, run_state):
    """The ClaudeAgentOptions for one machine session (R3/R1: tool surface,
    in-process verifier hook, static machine settings)."""
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

    return ClaudeAgentOptions(
        cli_path=cfg.claude_bin,
        cwd=cfg.repo_root,
        setting_sources=["project"],
        settings=f"{cfg.repo_root}/.claude/settings.stanok.json",
        permission_mode="dontAsk",
        # R3: `tools` -> `--tools` restricts the session's tool surface to
        # exactly cfg.curated_tools (the CLI's default set is NOT added on top);
        # allowed_tools is kept as the permission-allow side of the same set.
        tools=cfg.curated_tools,
        allowed_tools=cfg.curated_tools,
        hooks={
            # R1: in-process PostToolUse verifier (replaces hooks/verifier.sh).
            # timeout > _HOOK_TEST_TIMEOUT_S so the hook's own 75 s test timeout
            # is the deterministic verdict, not the SDK's hook timeout.
            "PostToolUse": [
                HookMatcher(matcher="Write|Edit",
                            hooks=[functools.partial(_verifier_hook, cfg)], timeout=90)
            ]
        },
        max_turns=cfg.max_agent_turns,
        model=cfg.model,
        env=build_agent_env(cfg, run_state),
    )


async def _interrupt_client(client) -> None:
    """Best-effort interrupt of the live SDK client; an interrupt error is a
    WARN, never a new failure (the run is already being failed closed)."""
    try:
        await client.interrupt()
    except Exception as e:
        log(f"WARN: client.interrupt() finished with an error: {e}")


async def _drain_turn_task(turn_task) -> None:
    """Post-timeout cleanup of the shielded turn task: give it 5 s to finish
    on its own (the interrupt may end it), then cancel and collect."""
    try:
        await asyncio.wait_for(asyncio.shield(turn_task), timeout=5.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    if not turn_task.done():
        turn_task.cancel()
    await asyncio.gather(turn_task, return_exceptions=True)


async def _turn_timeout_verdict(client, turn_task, job: dict, turn: int,
                               cfg) -> int:
    """Silent-stall timeout: interrupt, drain the shielded task, fail closed
    with the TURN-TIMEOUT code."""
    log(f"TIMEOUT: turn {turn} exceeded {cfg.turn_timeout_s:.0f}s (silent stall) -> interrupt")
    await _interrupt_client(client)
    await _drain_turn_task(turn_task)
    job["error"] = f"TURN-TIMEOUT ({cfg.turn_timeout_s:.0f}s)"
    job["verifier"] = "FAIL"
    job["turns"] = turn
    return 1


def _record_turn_telemetry(job: dict, total_tokens: dict, result: TurnResult,
                          turn: int, elapsed_turn: float) -> int:
    """Cumulative token & cache telemetry for one finished turn (guarantee 4).

    Updates total_tokens in place, recomputes job["tokens"]/job["cache_hit_rate"],
    appends the turn_telemetry entry, logs the turn line. Returns live_context:
    the prompt size on the LAST API call (not the turn's cumulative usage) —
    the real context the model had to attend to (CONTEXT-ROT input).
    """
    inp = result.usage.get("input_tokens", 0)
    out = result.usage.get("output_tokens", 0)
    c_read = result.usage.get("cache_read_input_tokens", 0)
    c_create = result.usage.get("cache_creation_input_tokens", 0)

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

    live_context = (
        result.live_window.get("input_tokens", 0)
        + result.live_window.get("cache_read_input_tokens", 0)
        + result.live_window.get("cache_creation_input_tokens", 0)
    ) or turn_input_context

    log(f"Turn {turn} finished in {elapsed_turn:.1f}s | "
        f"Turn tokens: in={inp}, out={out}, cache_hit={c_read} ({turn_hit_rate:.1f}%) | "
        f"live window: {live_context} | "
        f"Session cache_hit: {session_hit_rate:.1f}%")

    # CC-234: the agent's own tooling activity (the Bash-success metric —
    # a PASS with bash_ok==0 is PASS-BLIND, not a clean acceptance).
    activity = job.setdefault("tool_activity", {"bash_total": 0, "bash_ok": 0})
    activity["bash_total"] += result.bash_total
    activity["bash_ok"] += result.bash_ok

    # CC-247: the test-fit proxy counters (typed, no gate — the summary
    # field is built by summary._test_fit_field from this job entry).
    fit = job.setdefault("test_fit", {"edits_after_green": 0, "new_tests_after_green": 0})
    fit["edits_after_green"] += result.test_edits_after_green
    fit["new_tests_after_green"] += result.test_new_tests_after_green

    job.setdefault("turn_telemetry", []).append({
        "turn": turn,
        "elapsed_s": round(elapsed_turn, 1),
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": c_read,
        "cache_creation_input_tokens": c_create,
        "live_context_tokens": live_context,
        "turn_hit_rate": round(turn_hit_rate, 1),
        "writes": result.writes,
        "bash_total": result.bash_total,
        "bash_ok": result.bash_ok,
    })

    # P1 telemetry (Opik analysis CC-302/CC-304, 2026-10-20): tag the
    # native compact_boundary events seen in this turn with its turn number
    # (the summary field is built by summary._compactions_field from this
    # job entry). Token totals above already EXCLUDE compaction calls;
    # this records that a compaction happened and at what window size.
    for c in result.compactions:
        job.setdefault("compactions", []).append({"turn": turn, **c})

    return inp, live_context


def _bash_selfcheck(job: dict) -> int | None:
    """CC-234 startup self-check (operator condition 2026-10-11): reproduce the
    CLI Bash tool's tmp root — CLAUDE_CODE_TMPDIR || /tmp, then
    "claude-<uid>" (cli.js 2.1.88) — BEFORE the model starts: mkdir + a probe
    file + `bash -c pwd` in it. The cc231/cc233 incident: under a read-only
    /tmp every Bash call died ENOENT, the agent wrote blind for the whole run
    and the host verdict was still PASS. Fail-closed here: ENV-FAIL (rc=16)
    before a single model token is spent. Returns None when OK."""
    root = os.environ.get("CLAUDE_CODE_TMPDIR") or "/tmp"
    probe_dir = os.path.join(root, f"claude-{os.getuid()}")
    probe_file = os.path.join(probe_dir, "stanok-selfcheck")
    try:
        os.makedirs(probe_dir, exist_ok=True)
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
        r = subprocess.run(["bash", "-c", "pwd"], cwd=probe_dir,
                           capture_output=True, timeout=10)
        if r.returncode != 0:
            raise OSError(f"bash exited {r.returncode}: "
                          f"{r.stderr.decode(errors='replace').strip()}")
    except (OSError, subprocess.SubprocessError) as e:
        log(f"ENV-FAIL: Bash self-check failed ({e}) — the CLI Bash tmp root "
            f"{probe_dir} is not usable; no model call was made")
        job["error"] = f"ENV-FAIL: Bash self-check failed: {e}"
        job["verifier"] = "FAIL"
        job["turns"] = 0
        return int(ExitCode.ENV_FAIL)
    return None


def _hook_selfcheck(cfg, job: dict) -> int | None:
    """CC-236 startup self-check (operator condition 2026-10-11): every
    command hook registered in the project settings (.claude/settings.json)
    must resolve to a real executable file. Incident cc235 (operator trace
    review): the CLI does not export CLAUDE_PROJECT_DIR for hooks (cli.js
    2.1.88 exports it only in plugin context); the registered PreToolUse
    command "$CLAUDE_PROJECT_DIR/.claude/hooks/loop-guard.py" expanded to
    "/.claude/hooks/loop-guard.py" -> exit 127 on EVERY tool call
    (num_non_blocking_error=1 in the trace) — the loop guard was dead and
    the verdict was still CLEAN-FIRST. The expansion mirrors what the CLI's
    hook shell will see: CLAUDE_PROJECT_DIR is exported by build_agent_env
    with exactly this value (cfg.repo_root). Fail-closed: ENV-FAIL (rc=16)
    before a single model token is spent. Returns None when OK."""
    settings_path = os.path.join(cfg.repo_root, ".claude", "settings.json")
    # Fail-closed split (external review 2026-10-16): ABSENT settings mean
    # no registered hooks — nothing to resolve, pass. EXISTING-but-broken
    # settings (unreadable, invalid JSON) mean the hooks they register are
    # unresolvable — the old single `except (OSError, ValueError): return
    # None` greenlit a corrupt settings.json, the exact file whose hooks
    # this check exists to guard (a corrupt file is also what the CLI would
    # choke on mid-run).
    try:
        with open(settings_path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None  # no project settings -> no registered hooks
    except OSError as e:
        log(f"ENV-FAIL: hook self-check failed — {settings_path} exists but "
            f"is unreadable ({e}); no model call was made")
        job["error"] = f"ENV-FAIL: hook self-check failed: settings unreadable: {e}"
        job["verifier"] = "FAIL"
        job["turns"] = 0
        return int(ExitCode.ENV_FAIL)
    try:
        settings = json.loads(text)
    except ValueError as e:
        log(f"ENV-FAIL: hook self-check failed — {settings_path} is not "
            f"valid JSON ({e}); registered hooks are unresolvable; no model "
            "call was made")
        job["error"] = (f"ENV-FAIL: hook self-check failed: settings.json is "
                        f"not valid JSON: {e}")
        job["verifier"] = "FAIL"
        job["turns"] = 0
        return int(ExitCode.ENV_FAIL)
    bad = []
    for group in (settings.get("hooks") or {}).values():
        for entry in group or []:
            for hook in entry.get("hooks") or []:
                if hook.get("type") != "command" or not hook.get("command"):
                    continue
                cmd = hook["command"].replace(
                    "${CLAUDE_PROJECT_DIR}", cfg.repo_root)
                cmd = cmd.replace("$CLAUDE_PROJECT_DIR", cfg.repo_root)
                for token in cmd.split():
                    token = token.strip("\"'")
                    if not token.startswith("/"):
                        continue  # inline shell command — nothing to resolve
                    if not (os.path.isfile(token) and os.access(token, os.X_OK)):
                        bad.append(token)
    if bad:
        log(f"ENV-FAIL: hook self-check failed — registered hook command(s) "
            f"resolve to no executable file: {bad}; no model call was made")
        job["error"] = f"ENV-FAIL: hook self-check failed: {bad}"
        job["verifier"] = "FAIL"
        job["turns"] = 0
        return int(ExitCode.ENV_FAIL)
    return None


async def run_continuous_session(cfg, run_state, job: dict, ticket_prompt: str,
                                max_retries: int, plan: "SessionPlan") -> int:
    from claude_agent_sdk import ClaudeSDKClient

    rc = _bash_selfcheck(job)
    if rc is not None:
        return rc

    rc = _hook_selfcheck(cfg, job)
    if rc is not None:
        return rc

    local_run_id = str(uuid.uuid4())[:8]
    stream_out_path = os.path.join(run_state.live_dir, f"session-{local_run_id}.jsonl")
    options = _agent_options(cfg, run_state)

    max_turns = 1 + max_retries
    current_prompt = ticket_prompt
    log(f"SESSION START (run_id: {local_run_id}) | Turn limit: {max_turns} | model={cfg.model}")

    total_tokens = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    job["tokens"] = total_tokens
    job["cache_hit_rate"] = "0.0%"

    # contract_lock (W2.5): snapshot the protected files before the session; a
    # pre-existing test file modified/deleted during the run is a violation in
    # summary.json (the :ro bind makes the modification impossible; the diff
    # still catches a deletion, i.e. a write to the parent dir).
    tests_manifest_before = _tests_manifest(cfg)

    with open(stream_out_path, "a", encoding="utf-8") as stream_f:
        async with ClaudeSDKClient(options=options) as client:
            for turn in range(1, max_turns + 1):
                log(f"\n>>> Turn {turn}/{max_turns} {'(Fixing errors in src/)' if turn > 1 else '(Ticket start)'} <<<")

                t0 = time.time()
                turn_task = asyncio.create_task(
                    _execute_turn(client, current_prompt, turn, stream_f, job, run_state, cfg)
                )

                # Shielded Turn Watchdog (guarantee 5): asyncio.shield keeps the
                # turn task alive past wait_for, so client.interrupt() runs
                # cleanly and the summary is written with the TURN-TIMEOUT code
                # without the process dying on CancelledError.
                try:
                    result = await asyncio.wait_for(asyncio.shield(turn_task), timeout=cfg.turn_timeout_s)
                except asyncio.TimeoutError:
                    return await _turn_timeout_verdict(client, turn_task, job, turn, cfg)

                # CC-237: telemetry BEFORE the trap branch. The trap turn is a
                # finished turn (the breaker ended it mid-way) — its usage,
                # tool_activity and turn_telemetry must reach the summary
                # (cc236 incident: LOOP-TRAP summary showed bash 0/0, tokens 0
                # because _loop_trap_verdict returned before _record_turn_telemetry).
                elapsed_turn = time.time() - t0
                inp, live_context = _record_turn_telemetry(job, total_tokens, result, turn, elapsed_turn)

                # CC-207: the loop-guard circuit breaker tripped mid-turn —
                # the model repeated one identical call 5x in a row and the
                # hook signalled termination. NO fix prompt, NO local retries:
                # a retry re-enters the same loop (the marker is cumulative
                # for the session). Interrupt the session best-effort, then
                # fail closed with probe_result "LOOP-TRAP".
                if result.loop_trap:
                    log(f"LOOP-TRAP (turn {turn}): {result.loop_trap.get('tool')!r} "
                        f"repeated {result.loop_trap.get('n')}x consecutively — "
                        "circuit breaker tripped, interrupting the session")
                    await _interrupt_client(client)
                    job["turns"] = turn
                    return _loop_trap_verdict(job, result.loop_trap)

                # The verdict pipeline (dead-session stop, contract_lock,
                # observability warnings, verify_gate, NO-OP/PASS/FAIL verdict,
                # fix prompt) is _post_turn_decision — see its docstring for
                # the order contract.
                rc, next_prompt = _post_turn_decision(
                    cfg, job, turn, max_turns, plan, result, tests_manifest_before,
                    inp, live_context)
                if rc is not None:
                    return rc
                current_prompt = next_prompt

    job["verifier"] = "FAIL"
    job["turns"] = max_turns
    return 1


# ==================================================================================
# Processes, signals, and artifacts
# ==================================================================================
def _install_signal_handlers(run_state) -> None:
    def handler(signum, _frame):
        run_state.interrupted_rc = 128 + signum
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

