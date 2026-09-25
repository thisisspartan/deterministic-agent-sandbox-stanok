#!/usr/bin/env python3
"""Stanok — context-engineered Runner on a local model.

Full integration with the L1 Supervisor:
  1. Single Continuous Session (ClaudeSDKClient): retries inside ONE session (99% KV cache).
  2. Strict summary.json contract (probe_result, c5, review_verdict, errors) for L1.
  3. Adaptive Contract Lock: adaptation for creating tests from scratch and a ban on weakening assertions.
  4. Cumulative Token & Cache Telemetry: exact session_hit_rate calculation.
  5. Shielded Turn Watchdog: the turn timeout (default 1800s) is a terminal DoS
     circuit breaker — asyncio.shield() keeps the turn task alive past wait_for,
     so client.interrupt() runs cleanly and summary.json is written with the
     TURN-TIMEOUT code (rc=1) without the process dying on CancelledError.
  6. Verifier-output compression: last-N raw tail, no pattern heuristics at
     all (REVIEW-KISS-CLI-FIRST §3.3; the last substring filter — CC-138).
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

try:
    import tomllib  # stdlib TOML (Python 3.11+); CC-151 manifest-driven guard
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

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


# T1 (CC-120): the single source of file policy (invariant I1). The policy
# consumers (parse/quarantine/contract_lock/verify_gate) read from this object;
# no consumer keeps a free-floating policy list. git is always ro. Neither the
# container's rw MOUNTS nor the :ro protected set is a field: the mounts are
# derived from mutable_paths by declared_carveout (T4/CC-135) and the :ro binds
# from the same manifest the post-turn diff hashes (host_ro_paths/T4b), so no
# list in the plan can drift from the ticket or go stale. (The T2 probe_specs
# placeholder was dropped when T2 was burned — CC-131; protected_paths was
# dropped with the PreToolUse hook it fed — T5/CC-137.)
@dataclasses.dataclass(frozen=True)
class SessionPlan:
    declared_paths:  tuple[str, ...]  # ticket header: impl:/test:/docs:/edit:
    mutable_paths:   tuple[str, ...]  # always == declared_paths (edit: paths included, CC-125)
    git_mode:        str = "ro"       # .git is always RO (I7, verified 2026-09-24)
    # CC-125: `edit:`-declared paths are MODIFIED IN PLACE, not created from
    # scratch — prepare_workspace must not quarantine them. They stay in
    # declared_paths/mutable_paths (positive contract + contract_lock exemption).
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


def _publish_evidence(label: str) -> None:
    """Copy the container-written verdict from the rw LOG_DIR/<label> into the
    host-owned evidence/<label> (CC-134).

    Called in run_sandboxed's finally AFTER docker stop — the container has no
    rw view of evidence/, so the host is the only publisher. Missing files are
    skipped: an aborted launch publishes nothing rather than a fake verdict."""
    src = os.path.join(LOG_DIR, label)
    files = ("summary.json", "launcher.stdout.log")
    if not any(os.path.isfile(os.path.join(src, f)) for f in files):
        return
    dst = os.path.join(REPO_ROOT, "evidence", label)
    os.makedirs(dst, exist_ok=True)
    for name in files:
        s = os.path.join(src, name)
        if os.path.isfile(s):
            shutil.copyfile(s, os.path.join(dst, name))


def _rotate_stale_summary(label: str) -> None:
    """Rotate a stale summary.json left by an EARLIER run of the same label
    (a run aborted at a gate after writing its report, or a killed process).
    Without rotation, early_abort's write-if-absent guard would keep the OLD
    report and the supervisor would read a verdict from the previous run.
    Only rotate when no `.running` marker is present: a live run's evidence
    must not be touched."""
    evidence_dir, _ = label_paths(label)
    marker = os.path.join(evidence_dir, ".running")
    sum_path = os.path.join(evidence_dir, "summary.json")
    if os.path.isfile(sum_path) and not os.path.exists(marker):
        try:
            os.replace(sum_path, sum_path + ".prev")
        except OSError:
            pass


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


def hidden_files_gate() -> bool:
    # W4 hygiene gate (fail-closed): reject a launch if src/tests/docs/scripts
    # holds, at ANY DEPTH, a hidden file or directory (name starting with '.',
    # except .gitkeep) or a file carrying a 'TEMP:' marker in its first 40
    # lines. Such leftovers from past runs leak into the machine's context (the
    # model reads them and derives requirements from them) and slip past
    # dirty_tree_gate (git status is clean for committed/ignored dotfiles).
    # Intentionally narrow (owner decision): only these two signals, not "any
    # undeclared file".
    #
    # CC-139: this used to os.listdir only the zone TOP level, so a hidden
    # leftover in a subdirectory (`src/pkg/.secret`) was invisible (audit
    # Appendix A #3). The walk is recursive; a hidden DIRECTORY is flagged too,
    # since it is the same class of leftover and a dot-dir holding only
    # non-hidden files (src/.cache/notes.md) would otherwise still leak.
    for d in sandbox.WRITABLE_ZONES:
        dirpath = os.path.join(REPO_ROOT, d)
        if not os.path.isdir(dirpath):
            continue
        walk_errors: list[OSError] = []
        for root, dirs, files in os.walk(dirpath, onerror=walk_errors.append):
            for name in dirs:
                if name.startswith(".") and name != ".gitkeep":
                    log(f"HIDDEN-DIR: {os.path.join(root, name)}")
                    return True
            for name in files:
                path = os.path.join(root, name)
                if name.startswith(".") and name != ".gitkeep":
                    log(f"HIDDEN-FILE: {path}")
                    return True
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        head = [f.readline() for _ in range(40)]
                except OSError:
                    log(f"WARN: read failed in hidden_files_gate for {path} — fail-closed (treating as flagged)")
                    return True
                if any("TEMP:" in line for line in head):
                    log(f"TEMP-MARKER: {path}")
                    return True
        if walk_errors:
            log(f"WARN: walk failed in hidden_files_gate under {dirpath}: "
                f"{walk_errors[0]} — fail-closed (treating as flagged)")
            return True
    return False


# CC-151: the pre-manifest (W6) py verdict-config set. Fail-closed fallback
# when no stack manifest parses (e.g. hermetic test repos with no
# scripts/stacks/), so the guard never silently disables.
_LEGACY_VERDICT_CONFIG = ("conftest.py", "pytest.ini", "tox.ini",
                         "setup.cfg", "pyproject.toml")


def _verdict_config_patterns() -> tuple[str, ...]:
    """CC-151 (stack-agnostic subversion guard): the union of the
    `verdict_config` lists declared by the stack manifests
    (scripts/stacks/*.toml). Each stack declares the config filenames that
    can rewrite ITS runner's verdict (py: the pytest config set; js/jq: none).
    The manifest is authoritative — a stack that declares no verdict_config
    does not inherit another stack's list. Fail-closed: if no manifest parses
    (missing dir, unparseable TOML, or tomllib unavailable) fall back to the
    legacy py set so the guard never silently disables."""
    if tomllib is None:
        return _LEGACY_VERDICT_CONFIG
    stacks_dir = os.path.join(REPO_ROOT, "scripts", "stacks")
    patterns: set[str] = set()
    found = False
    ok = True
    try:
        entries = sorted(os.listdir(stacks_dir))
    except OSError:
        entries = []
    for entry in entries:
        if not entry.endswith(".toml"):
            continue
        found = True
        path = os.path.join(stacks_dir, entry)
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            log(f"WARN: verdict_config: cannot parse {entry}: {e}")
            ok = False
            continue
        for name in data.get("verdict_config", []):
            if isinstance(name, str) and name:
                patterns.add(name)
    if not found or not ok:
        return _LEGACY_VERDICT_CONFIG
    return tuple(sorted(patterns))


def test_config_gate() -> bool:
    # W6 verdict-subversion gate (owner decision A, fail-closed); CC-151 makes
    # it stack-agnostic: the forbidden set is the union of the `verdict_config`
    # lists declared by the stack manifests (scripts/stacks/*.toml), not a
    # hardcoded py tuple. A config file that can rewrite a runner's verdict
    # (e.g. a conftest.py with `pytest_sessionfinish: session.exitstatus = 0`
    # turning a failing test into rc=0) is rejected at launch (rc=27). tests/
    # is writable and contract_lock only hashes files that existed at start,
    # so such a file can appear mid-project; the runner picks up config from
    # every directory on the test file's path, hence the recursive walk.
    tests_dir = os.path.join(REPO_ROOT, "tests")
    if not os.path.isdir(tests_dir):
        return False
    forbidden = _verdict_config_patterns()
    try:
        for dirpath, _dirnames, filenames in os.walk(tests_dir):
            for name in filenames:
                if name in forbidden:
                    log(f"TEST-CONFIG: {os.path.join(dirpath, name)}")
                    return True
    except OSError:
        log("WARN: walk failed in test_config_gate — fail-closed (treating as flagged)")
        return True
    return False


def sandbox_config_gate() -> list[str]:
    # W7 sandbox-config gate (fail-closed, CC-107): cli.js resolves a relative
    # sandbox.filesystem deny entry against the --settings file's directory
    # (REPO_ROOT/.claude), NOT cwd. A deny entry that resolves to a NON-EXISTENT
    # path makes cli.js emit `--ro-bind /dev/null <path>`; bwrap must create the
    # mount point, and on the read-only repo mount that is EROFS for EVERY Bash
    # call in the session (CC-107). A non-existent deny entry is always a mistake
    # (typo / wrong base), so fail-closed if any denyWrite/denyRead entry does
    # not exist.
    #
    # We do NOT reimplement cli.js's resolver: this config only uses
    # settings-relative entries (written "../<name>" from .claude) and absolute
    # paths. Any other form ("~", "//") is rejected rather than guessed at, so
    # the gate cannot silently diverge from cli.js semantics.
    #
    # Returns a list of human-readable problems (empty = OK). Each problem
    # names the key, the raw entry, the resolved path, and the fix
    # (CC-157: the rc=28 abort must be actionable, not abstract).
    problems: list[str] = []
    settings = os.path.join(REPO_ROOT, ".claude", "settings.stanok.json")
    if not os.path.isfile(settings):
        return problems
    try:
        with open(settings, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        problems.append(f"could not parse {settings}: {e}")
        return problems
    base = os.path.dirname(settings)  # == REPO_ROOT/.claude (cli.js flagSettings root)
    fs = cfg.get("sandbox", {}).get("filesystem", {})
    for key in ("denyWrite", "denyRead"):
        for entry in fs.get(key, []):
            if entry.startswith(("~", "//")):
                problems.append(
                    f"{key} entry {entry!r} is not settings-relative/absolute (unsupported)")
                continue
            resolved = entry if os.path.isabs(entry) else os.path.normpath(os.path.join(base, entry))
            if not os.path.exists(resolved):
                problems.append(
                    f"{key} entry {entry!r} resolves to non-existent {resolved} "
                    f"(base {base}) — fix: mkdir -p {resolved}")
    for p in problems:
        log(f"SANDBOX-CONFIG: {p}")
    return problems


def _required_context_window() -> int | None:
    """Required context window, from the env only: STANOK_REQUIRED_WINDOW
    (exported by P0-launch.sh). cli.js likewise reads
    CLAUDE_CODE_AUTO_COMPACT_WINDOW from env (rQ); there is no settings source —
    the former .claude/settings.stanok.json fallback read a key that no longer
    exists (CC-127)."""
    env_val = os.environ.get("STANOK_REQUIRED_WINDOW")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            log(f"WARN: STANOK_REQUIRED_WINDOW={env_val!r} is not an integer; ignoring")
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


def _stack_preflights() -> list[str]:
    """The 6th (preflight) field of each STACKS registry line in
    scripts/run.sh — the cheap per-stack runner-availability probe
    (e.g. `uv run --no-project pytest --version`)."""
    try:
        with open(os.path.join(REPO_ROOT, "scripts", "run.sh"), encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return []
    m = re.search(r"^STACKS='(.*?)'$", src, re.M | re.S)
    if not m:
        return []
    preflights = []
    for line in m.group(1).splitlines():
        parts = line.split("|")
        if len(parts) >= 6 and parts[5].strip():
            preflights.append(parts[5].strip())
    return preflights


def _image_digest() -> str:
    """sha256 over the image-defining sources: Dockerfile + scripts/run.sh
    (the STACKS registry). setup.sh bakes this into the image LABEL
    stanok.digest at build time; preflight_image() re-computes it in
    doctor (CC-106: moved off the launch path)."""
    h = hashlib.sha256()
    for rel in ("Dockerfile", "scripts/run.sh"):
        with open(os.path.join(REPO_ROOT, rel), "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def preflight_image(image: str) -> bool:
    """Host-side image provenance + runner preflight.
    1. The image LABEL stanok.digest must equal sha256(Dockerfile + run.sh)
       — an image older than the Dockerfile/registry is caught here,
       not mid-run.
    2. Each stack's preflight command must succeed INSIDE the image
       (docker run --rm) — the runner is available where the tests run.
    CC-106: no longer on the launch path (the former blocking rc=25 is
    freed) — doctor calls it (test_doctor.py::test_docker_image_digest_matches).
    Fail-closed: any docker error, missing label, or failed probe returns
    False."""
    try:
        want = _image_digest()
    except OSError as e:
        log(f"PREFLIGHT-IMAGE: cannot compute image digest: {e} (doctor image preflight)")
        return False
    try:
        out = subprocess.run(
            ["docker", "inspect", "--format",
             '{{index .Config.Labels "stanok.digest"}}', image],
            capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            log(f"PREFLIGHT-IMAGE: image {image} not found (doctor image preflight)")
            return False
        got = out.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        log(f"PREFLIGHT-IMAGE: docker inspect failed: {e} (doctor image preflight)")
        return False
    if got != want:
        log(f"PREFLIGHT-IMAGE: digest mismatch — image label {got!r} != "
            f"sha256(Dockerfile+run.sh) {want!r}; rebuild via ./setup.sh (doctor image preflight)")
        return False
    log(f"PREFLIGHT-IMAGE: digest OK ({want[:12]}…)")
    for pre in _stack_preflights():
        try:
            p = subprocess.run(
                ["docker", "run", "--rm", image, "/bin/sh", "-c", pre],
                capture_output=True, text=True, timeout=60)
            if p.returncode != 0:
                log(f"PREFLIGHT-IMAGE: runner unavailable in image: {pre!r} "
                    f"(probe rc={p.returncode}) (doctor image preflight)")
                return False
        except (OSError, subprocess.SubprocessError) as e:
            log(f"PREFLIGHT-IMAGE: docker run failed for {pre!r}: {e} (doctor image preflight)")
            return False
    log("PREFLIGHT-IMAGE: all stack runners available in the image — OK")
    return True


def _opik_trace_count() -> int | None:
    """Total trace count in the 'stanok' Opik project, or None if Opik is
    unreachable. The machine exports OTLP spans to the host Opik backend
    (network=host -> localhost:8080). CC-106: sampled ONCE, fast, strictly
    after the verdict is formed (no pre-run baseline, no settle loop) — an
    unreachable backend (None) never delays or alters the run."""
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


def declared_carveout(rel: str) -> str | None:
    """The rw-mount carve-out a declared path implies, or None if the path is
    undeclarable (T4, CC-135 — one rule for the gate AND the mounts).

    Literal declared paths are ticket-supplied input: prepare_workspace's
    quarantine shutil.move()s them (so an unvalidated `impl: /etc/passwd` could
    destroy host files) and the container binds them rw. Fail-closed:

      - relative, no `..`, no symlink resolving OUTSIDE the repo (Docker
        resolves a bind source's realpath, so a link inside the repo could
        smuggle an outside dir in — run.sh already refuses symlinked test
        paths, SEC-01);
      - a bare zone name (`src`, `tests/`) is not a file -> None (quarantine
        would move the whole zone out of the tree);
      - the path exists (file or dir) -> itself: a per-file/per-dir rw bind;
      - the path is absent -> its NEAREST EXISTING ANCESTOR dir, which must be
        BELOW the repo root. Docker creates a missing bind SOURCE as a
        root-owned DIRECTORY (verified 2026-09-24), so an absent path cannot
        be file-bound at all; and binding the repo root itself rw would
        dissolve the whole boundary -> None.
    """
    if rel.startswith("/") or rel.startswith("./"):
        return None
    if ".." in rel.split("/"):
        return None
    if rel.rstrip("/") in sandbox.WRITABLE_ZONES:
        return None
    root = os.path.realpath(REPO_ROOT)
    if not os.path.realpath(os.path.join(root, rel)).startswith(root + os.sep):
        return None
    if os.path.exists(os.path.join(root, rel)):
        return rel
    carve = os.path.dirname(rel)
    while carve:
        if os.path.isdir(os.path.join(root, carve)):
            return carve
        carve = os.path.dirname(carve)
    return None


def _validate_declared_path(rel: str) -> bool:
    """parse_ticket_header's gate: a path is declarable exactly when the
    filesystem can back its rw carve-out (declared_carveout)."""
    return declared_carveout(rel) is not None


def host_ro_paths(declared: list[str], rw_paths: tuple) -> tuple[str, ...]:
    """The pre-existing contract files to re-bind `:ro` ON TOP of a rw carve-out
    (T4b, CC-136).

    A carve-out that is a DIRECTORY hands back write access to every
    pre-existing file in it — and since an absent declared path can only be
    carved out through its parent dir, declaring a NEW test would otherwise make
    every reference test in tests/ writable at the filesystem layer. Docker
    layers a file bind over a dir bind by specificity (verified 2026-09-24), so
    binding the protected files :ro restores immutability natively — this is the
    FIRST echelon; the post-turn manifest diff (T5/CC-137) is the second.

    Two exclusions: a file outside every carve-out needs no bind (the repo `:ro`
    mount already covers it), and a DECLARED path is never bound (`edit:` on an
    existing test is exactly the case that must stay writable)."""
    declared_set = set(declared)
    ro: list[str] = []
    for rel in _protected_files():
        if rel in declared_set:
            continue
        if not any(rel == carve or rel.startswith(carve + "/")
                   for carve in rw_paths):
            continue
        ro.append(rel)
    return tuple(ro)


def host_rw_paths(declared: list[str]) -> tuple[str, ...]:
    """The deduped rw carve-outs for a declared-path list — what the HOST
    passes to sandbox_argv before `docker run` (T4). The declared paths were
    validated by parse_ticket_header, so every carve-out is non-None here."""
    carveouts: list[str] = []
    for rel in declared:
        carve = declared_carveout(rel)
        if carve is not None and carve not in carveouts:
            carveouts.append(carve)
    return tuple(carveouts)


def parse_ticket_header(ticket_text: str) -> tuple[list[str], list[str], bool]:
    """Ticket-scoped invariant (W2.1): the header is the leading block of
    literal `impl: <path>` / `test: <path>` / `docs: <path>` / `edit: <path>`
    lines plus an optional `reset: none` escape hatch for extension tickets.
    `#` title lines and blank lines are skipped inside the header block; the
    first other line ends it (a path mentioned in the body is never matched).

    `edit:` marks a path that the ticket MODIFIES IN PLACE (typically an
    existing test whose contract changes) — it is declared like any other path
    but is NOT quarantined (CC-125). Paths are validated against the
    filesystem (declared_carveout: relative, no `..`, no symlink out of the
    repo, and an existing path or an existing ancestor BELOW the repo root);
    an undeclarable path raises ValueError (fail-closed, rc=13 upstream).

    Returns (declared_paths, edit_paths, reset_none); declared_paths is the
    union (edit paths included), so mutable_paths/verify_gate are unchanged."""
    entries: list[tuple[str, str]] = []
    reset_none = False
    for line in ticket_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _FILE_LINE_RE.match(stripped)
        if m:
            entries.append((m.group(1), m.group(2)))
            continue
        if _RESET_NONE_RE.match(stripped):
            reset_none = True
            continue
        break
    declared: list[str] = []
    edit_paths: list[str] = []
    for kind, rel in entries:
        if not _validate_declared_path(rel):
            raise ValueError(
                f"invalid declared path {rel!r}: must be relative, contain no "
                f"'..', resolve inside the repo (no symlink out), and either "
                f"exist or lie under an existing directory (e.g. under "
                f"{list(sandbox.WRITABLE_ZONES)}, created in the repo if it is "
                f"absent) — a NEW top-level file/dir has no safe rw carve-out"
            )
        if kind == "edit":
            edit_paths.append(rel)
        declared.append(rel)
    return declared, edit_paths, reset_none


def assert_create_paths_are_new(declared: list[str], edit_paths: list[str]) -> None:
    """CC-133: create-vs-edit is a header CLAIM that nothing used to verify.

    A path declared as a create (`impl:`/`test:`/`docs:`) that ALREADY EXISTS
    is a ticket defect, and it used to fail in the worst possible way: the
    quarantine moved the file aside, the agent then had to edit a path that no
    longer held the old content, the contract-lock hook denied recreating it,
    and the turn died on the 1800 s watchdog (CC-119 fire16: a pre-existing
    test declared as `test:`; retry1 `rc=143` + a 1800 s stall).

    Derive the kind from the filesystem instead of trusting the header: raise
    ValueError (fail-closed, rc=13 upstream) naming the path and the fix.

    Only this direction is checked. `edit:` on a path that does NOT exist is
    left alone: it is not silently destructive (the agent just creates it), and
    a first ticket in a new project may legitimately declare
    `edit: scripts/run.sh` before run.sh exists."""
    skip = set(edit_paths)
    for rel in declared:
        if rel in skip:
            continue
        if os.path.exists(os.path.join(REPO_ROOT, rel)):
            raise ValueError(
                f"declared path {rel!r} already exists but is declared as a create "
                f"(impl:/test:/docs:); declare it as `edit: {rel}` to modify it in "
                f"place, or remove the stale artifact"
            )


def prepare_workspace(plan: "SessionPlan") -> int:
    # SEC-01: .git is read-only inside the container — NO git writes here.
    # The cleanliness gate is dirty_tree_gate() (single source, called by main()
    # rc=22). This function only prepares the writable workspace.
    #
    # CC-135: the former zone-makedirs loop is gone. It existed because the
    # zone dirs were the rw mount points (a missing mount point would have been
    # created root-owned). T4 derives the carve-outs from the ticket and refuses
    # a declared path with no existing carve-out, so every dir the run needs
    # already exists — and inside the container a makedirs of a non-carved-out
    # zone would now be an EROFS error, not a no-op.
    try:
        # Ticket-scoped invariant (W2.2): QUARANTINE (not delete) the artifacts
        # the ticket declares, so the run starts in a state where they do not
        # exist. Non-destructive: moved to _live_dir/pre-existing/ (outside the
        # repo — dirty_tree_gate is unaffected). Called ONCE before the session:
        # retries never wipe the model's work.
        # CC-125: `edit:`-declared paths are the exception — the ticket modifies
        # them IN PLACE (e.g. an existing test whose contract changes), so moving
        # them aside would force a "recreate verbatim from git show" dance.
        quarantined = []
        for rel in plan.declared_paths:
            if rel in plan.edit_paths:
                continue
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
    """Compress verifier output for the fix prompt: keep the LAST lines (a test
    failure is reported at the tail).

    No pattern heuristics at all: neither the old JS/TAP-weighted priority
    regex (HANDOFF-ARCH-REVIEW §3 #9) nor a noise-line filter remains — a raw
    tail cannot pick the wrong window or hide a line the model needs
    (REVIEW-KISS-CLI-FIRST §3.3; the last `node_modules/` filter was the §1#1
    leftover, CC-138).
    """
    lines = raw_text.strip().splitlines()

    if len(lines) > MAX_TEST_LINES:
        start = len(lines) - MAX_TEST_LINES
        lines = [f"... [{start} lines skipped above] ..."] + lines[start:]
    res = "\n".join(lines)

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
        if p.returncode == 6:
            # ENV-FAIL: the runner is unavailable in the image — tagged so
            # verify_gate can fail-closed WITHOUT a fix prompt (rc=16).
            raw_err = (p.stderr or "") + "\n" + (p.stdout or "")
            return (rel, "ENV-FAIL: " + _extract_smart_diff(raw_err))
        if p.returncode == 124:
            # The test HUNG (run.sh's 60 s runner timeout). Tagged like
            # ENV-FAIL so the fix prompt gets the timeout rules, not the
            # generic "fix src exclusively" block (retry-loop DoS: the model
            # iterates on src/, the test hangs again, same prompt again).
            raw_err = (p.stderr or "") + "\n" + (p.stdout or "")
            return (rel, "TIMEOUT: test hung (rc=124) — " + _extract_smart_diff(raw_err))
        if p.returncode != 0:
            raw_err = (p.stderr or "") + "\n" + (p.stdout or "")
            return (rel, _extract_smart_diff(raw_err))
    except subprocess.TimeoutExpired:
        return (rel, "TIMEOUT: test execution exceeded the runner limit")
    except Exception as e:
        return (rel, f"EXEC_ERROR: {e}")
    return None


def _run_suite(failures: list[tuple[str, str]], tests: list[str]) -> None:
    """D4 (CC-149): run the whole suite in ONE `test --all` call instead of
    N per-file spawns. The suite runs every list-discovered file sequentially
    with per-file timeouts and `=== <file> ===` headers; rc maps:
      0   -> all pass (no failures appended)
      1   -> a test failed (or unclaimed file) -> one (suite) failure w/ output
      2   -> run.sh refused `--all` (no suite mode) -> per-file fallback
      6   -> ENV-FAIL (runner unavailable) -> tagged for fail-closed rc=16
      124 -> a file hit the 60 s timeout (suite stopped) -> tagged TIMEOUT

    Per-file attribution: the combined output carries `=== <file> ===`
    headers, so the fix-prompt diff shows which file failed; the model can
    re-run `test <file>` to localize. The pre-CC-149 per-file spawns are kept
    as the rc=2 fallback so an old entrypoint without suite mode still
    verifies (and `_run_one_test` stays the per-file primitive).
    """
    try:
        sp = subprocess.run(["bash", "scripts/run.sh", "test", "--all"],
                            cwd=REPO_ROOT, capture_output=True, text=True,
                            timeout=len(tests) * 60 + 60)
    except subprocess.TimeoutExpired:
        failures.append(("(suite)",
                         "TIMEOUT: suite execution exceeded the runner limit"))
        return
    except Exception as e:
        failures.append(("(suite)", f"EXEC_ERROR: {e}"))
        return
    rc = sp.returncode
    raw = (sp.stderr or "") + "\n" + (sp.stdout or "")
    if rc == 0:
        return
    if rc == 6:
        failures.append(("(suite)", "ENV-FAIL: " + _extract_smart_diff(raw)))
        return
    if rc == 124:
        failures.append(("(suite)",
                         "TIMEOUT: suite hit the per-file 60 s timeout "
                         "(rc=124) — " + _extract_smart_diff(raw)))
        return
    if rc == 2:
        # run.sh does not support `test --all` (pre-CC-149): fall back to
        # per-file spawns so an old entrypoint still verifies.
        with ThreadPoolExecutor(max_workers=min(8, len(tests))) as ex:
            futures = {ex.submit(_run_one_test, t): t for t in tests}
            for fut in as_completed(futures):
                res = fut.result()
                if res is not None:
                    failures.append(res)
        return
    # rc == 1 (a test failed / unclaimed file) or any other non-zero rc:
    # surface the suite output so the fix prompt can localize the failure.
    failures.append(("(suite)", _extract_smart_diff(raw)))


def verify_gate(plan: "SessionPlan") -> tuple[bool, list[tuple[str, str]], bool]:
    """Verdict = positive contract on the ticket's declared paths (W2.3)
    + every test the project's runner declares (D3).

    Discovery goes through the project entrypoint too (run.sh list), so the
    machine no longer hardcodes the *.test.js convention. Test execution is
    ONE whole-suite call per turn (`run.sh test --all`, D4/CC-149) instead of
    N per-file spawns; see `_run_suite` for the rc mapping and the rc=2
    per-file fallback.
    Returns (ok, failures, env_fail): env_fail is True when any failure is
    an ENV-FAIL (run.sh rc=6, runner unavailable) — an environment defect
    the model cannot fix from src/, so the caller must stop fail-closed
    (rc=16) instead of sending a fix prompt.
    """
    failures: list[tuple[str, str]] = []
    # Positive contract: every artifact the ticket declares must exist.
    # Closes the hole where a model that skipped docs/<m>.md still passed.
    for rel in plan.declared_paths:
        if not os.path.exists(os.path.join(REPO_ROOT, rel)):
            failures.append((rel, f"MISSING: declared by the ticket but not created: {rel}"))

    try:
        lp = subprocess.run(["bash", "scripts/run.sh", "list"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return (False, [("(no tests)", f"run.sh list failed: {e}")], False)
    tests = [ln.strip() for ln in (lp.stdout or "").splitlines() if ln.strip()]
    if not tests:
        if lp.returncode != 0:
            # `list` failed and printed no tests (no tests/ dir, or only
            # unclaimed files): the reason is on stderr — surface it instead
            # of the generic "no tests" message.
            failures.append(("(list)", _extract_smart_diff(lp.stderr)))
            return (False, failures, False)
        if failures:
            return (False, failures, False)
        return (False, [("(no tests)", "The project runner declares no tests")], False)
    if lp.returncode != 0:
        # W12: `list` fails closed (rc=1) on an unclaimed test-like file while
        # still printing the claimed tests on stdout. The unrun test must not
        # pass the gate silently: record the listing failure, then still run
        # the claimed tests (their failures add signal to the fix prompt).
        failures.append(("(list)", _extract_smart_diff(lp.stderr)))

    _run_suite(failures, tests)
    failures.sort(key=lambda x: x[0])
    env_fail = any(msg.startswith("ENV-FAIL:") for _, msg in failures)
    return (len(failures) == 0, failures, env_fail)


def _fix_prompt_rules(failures: list[tuple[str, str]]) -> str:
    """Select the fix-prompt rule block for a verify_gate failure set.

    Priority: list-fail > timeout > no-tests > generic. A hung test
    (TIMEOUT) must not get the generic "fix src exclusively" rules: that
    wording is a retry-loop DoS (the model iterates on src/, the test
    hangs again, verify_gate fails again with the same prompt).
    """
    has_list_fail = any(name == "(list)" for name, _ in failures)
    has_timeout_fail = any(msg.startswith("TIMEOUT:") for _, msg in failures)
    has_no_tests = any(name == "(no tests)" for name, _ in failures)
    if has_list_fail:
        return (
            "1. The project runner's `list` command failed: tests/ contains a test-like file that no registry line in scripts/run.sh claims.\n"
            "2. Delete the unclaimed file or move it to tests/fixtures/ (or tests/data/). It is CATEGORICALLY FORBIDDEN to add a registry line to scripts/run.sh to claim it, and to weaken or modify the tests in tests/.\n"
            "3. Then re-check with `bash scripts/run.sh list` — it must exit 0."
        )
    if has_timeout_fail:
        return (
            "1. A test HUNG (rc=124, runner timeout) — this is NOT a red assertion; do not iterate on src/ to make it green.\n"
            "2. Locate and remove the hang (infinite loop / blocking call) in the test or in the implementation.\n"
            "3. Then re-check with `bash scripts/run.sh test <path>` — it must finish well under the runner timeout."
        )
    if has_no_tests:
        return (
            "1. There are no test files in the tests/ directory! Create the reference tests strictly per the ticket specification.\n"
            "2. Then implement the corresponding working module code in the src/ directory."
        )
    return (
        "1. The tests in tests/ are the reference specification of the ticket. It is CATEGORICALLY FORBIDDEN to delete, modify, or weaken assertions in tests/.\n"
        "2. Fixes are made EXCLUSIVELY in the module implementations in the src/ directory.\n"
        "3. Study the diff and stack above, localize the error in src/ and eliminate the root cause of the bug."
    )


def _protected_files() -> list[str]:
    """The pre-existing contract files — the ONE source for "protected"
    (CC-136): tests/** plus scripts/run.sh. Both the contract_lock manifest and
    the host's :ro bind list (host_ro_paths) read this list, so the two cannot
    drift.

    Only PRE-EXISTING files: a missing scripts/run.sh (a new project's first
    ticket) is free to create. __pycache__/ is skipped: .pyc files are
    interpreter cache artifacts, not contract files — locking them makes a
    routine `rm -rf __pycache__` (or their regeneration) a false
    DELETED/MODIFIED violation (w12-verify)."""
    protected: list[str] = []
    tests_dir = os.path.join(REPO_ROOT, "tests")
    if os.path.isdir(tests_dir):
        for root, dirs, files in os.walk(tests_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                protected.append(os.path.relpath(os.path.join(root, name), REPO_ROOT))
    if os.path.isfile(os.path.join(REPO_ROOT, "scripts", "run.sh")):
        protected.append("scripts/run.sh")
    return protected


def _tests_manifest() -> dict[str, str]:
    """Snapshot {rel_path: sha256} of the protected files (contract_lock,
    W2.5 + P2) — see _protected_files for which files and why."""
    manifest: dict[str, str] = {}
    for rel in _protected_files():
        try:
            with open(os.path.join(REPO_ROOT, rel), "rb") as f:
                manifest[rel] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            manifest[rel] = "unreadable"
    return manifest


def _check_contract_lock(before: dict[str, str], job: dict, turn: int,
                         plan: "SessionPlan") -> None:
    """After each turn: a pre-existing protected file (tests/, scripts/run.sh)
    that was MODIFIED or DELETED is a contract_lock violation (replaces the
    chmod a-w freeze, W2.5). New files are allowed (a ticket may declare
    several). A mutable path is exempt (runner-update ticket, P2; T1:
    mutable_paths == declared_paths — behavior-identical to the old
    scripts/run.sh exemption, since the manifest is snapshotted AFTER
    quarantine and a mutable path is therefore never in the manifest)."""
    after = _tests_manifest()
    violations = []
    for rel, digest in before.items():
        if rel in plan.mutable_paths:
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


def _contract_lock_forced_fail(job: dict, turn: int) -> int | None:
    """Fail-closed on contract_lock violations (W2.5 + P2): a non-empty
    cumulative violations list means the machine MODIFIED/DELETED a
    pre-existing protected file (tests/, scripts/run.sh) after the manifest
    snapshot — a verify_gate PASS was computed against tampered tests and is
    not a PASS. No retry: the list is cumulative and can never be cleared
    inside the session, so a fix prompt cannot succeed; the supervisor
    relaunches with a refined ticket. Returns the run rc (1) or None when
    clean."""
    violations = job.get("contract_lock_violations") or []
    if not violations:
        return None
    job["verifier"] = "FAIL"
    job["error"] = ("CONTRACT-LOCK: the machine modified or deleted protected "
                   "files (tests/, scripts/run.sh) after the manifest snapshot "
                   "— the verdict was computed against tampered tests")
    job.setdefault("failures", []).extend(
        ("(contract_lock)", v) for v in violations
    )
    job["turns"] = turn
    log("CONTRACT-LOCK: fail-closed (no retry — violations are cumulative)")
    return 1


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
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "128000"),
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


async def _execute_turn(client, prompt: str, turn: int, stream_f, job: dict) -> tuple[dict, dict, int, str]:
    """Returns (turn_total, live_window, writes, turn_error).

    turn_total  — ResultMessage.usage: cumulative across the turn's API calls
                  (for session totals).
    live_window — the last AssistantMessage.usage: the prompt size actually sent
                  on the final API call (the true context window, for CONTEXT-ROT).
    writes      — count of Write/Edit tool_use blocks in the turn (NO-OP assert,
                  W2.4; immune to test side effects, unlike a file manifest).
    turn_error  — "" on a clean turn; otherwise the API/max-turns error string
                  (CLI_MAX_TURNS_EXCEEDED or the ResultMessage error detail).
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
                if getattr(block, "name", None) in ("Write", "Edit"):
                    writes += 1

        _write_stream_msg(stream_f, turn, msg)
    return (turn_total or live_window), live_window, writes, turn_error


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


async def _verifier_hook(hook_input: dict, tool_use_id: "str | None", context) -> dict:
    # W8 double-hook diagnosis: log EVERY invocation with its tool_use_id.
    # After a run: grep 'HOOK-CALL' <launcher log> | awk id | sort | uniq -d —
    # duplicate ids = double registration/call; unique ids = the second
    # callback is internal. Keep this log until the verdict is in CONTEXT.md.
    _ti = hook_input.get("tool_input") or {}
    log(f"HOOK-CALL id={tool_use_id} file={_ti.get('file_path')}")
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
        # Read into a shared list: a cancelled wait_for discards the read
        # task's LOCAL state (a communicate() that was cancelled had already
        # consumed the pre-kill bytes into its own locals — they were lost).
        # Chunks delivered before the deadline survive in `chunks` (bug 6:
        # the timeout message must show what the test printed before it hung).
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
        out = b"".join(chunks)
        # rc=0: GREEN (implementation exists) — stay silent.
        # rc=2: runner refused the path (not a test in its terms) — not our concern.
        # rc=6: ENV-FAIL (runner unavailable in the image) — an environment
        #       failure, NOT a red test; emitting RED here is what burned a
        #       whole turn on CC-081 ("fix" the environment from src/).
        if rc in (0, 2, 6):
            if rc == 6:
                log(f"VERIFIER HOOK: ENV-FAIL ({rel} rc=6) — runner unavailable, no RED")
            return {}
        text = out.decode("utf-8", "replace")
        tail = "\n".join(text.splitlines()[-25:])
        if rc == 124:
            # rc=124: the test HUNG (run.sh's 60 s runner timeout, or this
            # hook's own backstop) — not a red assertion. "Implement src/ to
            # make it GREEN" here is a retry-loop DoS: the model iterates on
            # src/, the test hangs again, the hook fires again. Name the
            # failure mode (hang) and where to look instead.
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
    except Exception as e:
        log(f"VERIFIER HOOK: no-op (error: {e})")
        return {}


async def run_continuous_session(job: dict, ticket_prompt: str, max_retries: int, plan: "SessionPlan") -> int:
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
        hooks={
            # R1: in-process PostToolUse verifier (replaces hooks/verifier.sh).
            # timeout > _HOOK_TEST_TIMEOUT_S so the hook's own 75 s test timeout
            # is the deterministic verdict, not the SDK's hook timeout.
            "PostToolUse": [
                HookMatcher(matcher="Write|Edit", hooks=[_verifier_hook], timeout=90)
            ]
        },
        max_turns=STANOK_MAX_AGENT_TURNS,
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

    # contract_lock (W2.5): snapshot the protected files before the session; a
    # pre-existing test file modified/deleted during the run is a violation in
    # summary.json (the :ro bind makes the modification impossible; the diff
    # still catches a deletion, i.e. a write to the parent dir).
    tests_manifest_before = _tests_manifest()

    with open(stream_out_path, "a", encoding="utf-8") as stream_f:
        async with ClaudeSDKClient(options=options) as client:
            for turn in range(1, max_turns + 1):
                log(f"\n>>> Turn {turn}/{max_turns} {'(Fixing errors in src/)' if turn > 1 else '(Ticket start)'} <<<")

                t0 = time.time()
                turn_task = asyncio.create_task(
                    _execute_turn(client, current_prompt, turn, stream_f, job)
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
                _check_contract_lock(tests_manifest_before, job, turn, plan)

                # PREFIX-BREAK alarm: a KV-prefix break shows up exactly as a
                # spike in the turn's input_tokens (uncached re-send). Only
                # meaningful from turn 2: on turn 1 there is no previous turn to
                # break the prefix from, so comparing the first prompt against a
                # constant baseline fired a false WARN on every run (CC-126).
                prev_inputs = [t["input_tokens"] for t in job["turn_telemetry"][:-1]]
                if prev_inputs:
                    median_prev = sorted(prev_inputs)[len(prev_inputs) // 2]
                    if inp > 2 * median_prev:
                        job["turn_telemetry"][-1]["prefix_break"] = True
                        log(f"  [PREFIX-BREAK WARN] turn {turn} input_tokens={inp} "
                            f"> 2x median of previous turns ({median_prev}) — KV prefix likely not reused")

                rot_threshold = context_rot_threshold()
                if live_context > rot_threshold:
                    log(f"  [CONTEXT-ROT WARN] Live context window ({live_context} tokens) "
                        f"exceeded the threshold {rot_threshold}. Model attention may degrade.")

                verify_ok, failures, env_fail = verify_gate(plan)

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
                    return 16

                # Fail-closed on contract_lock (W2.5 + P2): a PASS computed
                # against tampered tests is not a PASS. Checked after env_fail
                # (an unavailable runner is an infrastructure defect, rc=16,
                # and takes precedence over a ticket defect).
                forced = _contract_lock_forced_fail(job, turn)
                if forced is not None:
                    return forced

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
                    rules = _fix_prompt_rules(failures)

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
    if rc == 16:
        # ENV-FAIL: the image lacks the test runner — an infrastructure
        # failure (rebuild the image), neither a defect nor a NO-OP.
        return "ENV-FAIL", "FAIL", "ENV-FAIL"
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
    log(f"STANOK RUNNER | Repo: {REPO_ROOT} | Label: {args.label}")
    if args.direct:
        log("--direct MODE: the ticket path is resolved relative to the repository")

    # Ticket-scoped invariant (W2.1): parse the header BEFORE any workspace
    # mutation. Fail-closed: no `impl:`/`test:`/`docs:`/`edit:` line and no
    # `reset: none` means the invariant cannot be enforced (the old false
    # CLEAN-FIRST returns); an invalid literal path — including a
    # create-declared path that already exists (CC-133) — is rejected the same
    # way, before any workspace mutation.
    try:
        with open(args.ticket_path, encoding="utf-8") as f:
            ticket_prompt = f.read().strip()
        declared_paths, edit_paths, reset_none = parse_ticket_header(ticket_prompt)
        # CC-133: the create/edit split is derived from the filesystem, not
        # trusted from the header (ValueError -> rc=13 below).
        assert_create_paths_are_new(declared_paths, edit_paths)
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
        job["error"] = ("ticket declares no `impl:`/`test:`/`docs:`/`edit:` "
                        "line and no `reset: none` — the ticket-scoped invariant "
                        "cannot be enforced (fail-closed)")
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 13
    if declared_paths:
        log(f"DECLARED PATHS: {declared_paths}")
    if edit_paths:
        log(f"EDIT-IN-PLACE PATHS (not quarantined): {edit_paths}")

    # T1 (CC-120): build the SessionPlan — the single source of file policy (I1).
    plan = SessionPlan(
        declared_paths=tuple(declared_paths),
        mutable_paths=tuple(declared_paths),
        git_mode="ro",
        edit_paths=tuple(edit_paths),
    )

    if not preflight_server():
        job["rc"] = 20
        job["error"] = f"Server unavailable ({SERVER_URL})"
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 20

    if prepare_workspace(plan) != 0:
        job["rc"] = 14
        job["error"] = "workspace prep error"
        write_summary(job, int(time.time()) - start_ts)
        if os.path.exists(_marker_path):
            try: os.remove(_marker_path)
            except OSError: pass
        return 14

    rc = 1
    try:
        rc = asyncio.run(run_continuous_session(job, ticket_prompt, args.local_retries, plan))
    except KeyboardInterrupt:
        rc = _INTERRUPTED_RC or 130
    except Exception as e:
        log(f"FATAL EXCEPTION: {e}")
        job["error"] = str(e)
        rc = 1
    finally:
        job["rc"] = rc
        # Post-run Opik check (CC-106): strictly AFTER the verdict is formed,
        # ONE fast best-effort sample of the project trace count. No baseline
        # poll before the session, no sleep/resample loop — Opik latency must
        # never delay the run. Any network/HTTP/timeout failure ->
        # opik_traces: null. rc and verifier are never touched here.
        opik_after = _opik_trace_count()
        if opik_after is None:
            job["opik_traces"] = None
            log("OPIK: post-run trace count unavailable (backend unreachable)")
        else:
            job["opik_traces"] = opik_after
            log(f"OPIK: project trace count after run = {opik_after}")
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
def _status_dict(label: str) -> dict:
    """The status JSON `status` prints — single source, also used by `wait`.

    Precedence: a live `.running` marker (running/dead) over a summary.json
    (done) over missing. `run_sandboxed` publishes the verdict BEFORE removing
    the marker, so the marker's disappearance implies a readable summary.
    """
    evidence_dir, _ = label_paths(label)
    marker = os.path.join(evidence_dir, ".running")
    summary = os.path.join(evidence_dir, "summary.json")

    if os.path.exists(marker):
        try:
            parts = open(marker, encoding="utf-8").read().split()
            start_ts = int(parts[0]) if len(parts) >= 1 else int(time.time())
            pid = int(parts[1]) if len(parts) >= 2 else 0
            alive = _pid_alive(pid) if pid > 0 else False
            return {"state": "running" if alive else "dead", "pid": pid,
                    "elapsed_s": int(time.time()) - start_ts}
        except (ValueError, OSError):
            return {"state": "dead", "error": "corrupted marker"}
    if os.path.exists(summary):
        try:
            data = json.load(open(summary, encoding="utf-8"))
            return {
                "state": "done",
                "rc": data.get("rc"),
                "verifier": data.get("verifier"),
                "probe_result": data.get("probe_result"),
                "turns": data.get("turns"),
                "session_id": data.get("session_id"),
                "cache_hit_rate": data.get("cache_hit_rate"),
                "elapsed_s": data.get("elapsed_s"),
                "errors": data.get("errors", [])
            }
        except Exception as e:
            return {"state": "done", "error": f"summary read error: {e}"}
    return {"state": "missing"}


def cmd_status(label: str) -> int:
    print(json.dumps(_status_dict(label)))
    return 0


WAIT_POLL_S = 5
WAIT_TIMEOUT_S = 2700  # 45 min — the cap §3 of CLAUDE.supervisor.md names


def cmd_wait(label: str, timeout_s: int = WAIT_TIMEOUT_S) -> int:
    """Block until the run reaches a terminal state, print its final status.

    This is the ONE primitive behind `run --background --follow` and the
    standalone `wait` subcommand (CC-140). It exists because the supervisor's
    former §3 made "poll until done" a separate Bash task that could simply not
    be issued: in the SMOKE-02 run the supervisor launched `--background`, wrote
    "waiting", and ended its turn WITHOUT the wait task, so no completion
    notification ever reached the TUI (evidence/smoke-tools was a PASS the whole
    time). Collapsing launch+wait into one background call makes the
    notification the verdict trigger — there is no step left to forget.

    Returns 0 once a terminal state (done/dead/missing) is observed, 124 if the
    run is still `running` at `timeout_s` (the §3 45-min cap). Either way the
    printed JSON is the same shape as `status`.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        st = _status_dict(label)
        if st.get("state") != "running":
            print(json.dumps(st))
            return 0
        if time.monotonic() >= deadline:
            print(json.dumps({"state": "timeout", "elapsed_s": st.get("elapsed_s")}))
            return 124
        time.sleep(WAIT_POLL_S)


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


def run_sandboxed(args, rw_paths: tuple, ro_paths: tuple) -> int:
    """Host-side sync run: supervise the Docker container (replaces
    sandbox-run.sh). The marker carries THIS process's pid — cmd_stop's
    killpg lands here, and the try/finally stops the container and removes
    the marker on every exit path (normal return, crash, signal).

    rw_paths are the per-ticket rw carve-outs (T4/CC-135, derived in main()
    from the same ticket text the container will parse); ro_paths are the
    protected files re-bound :ro over a carve-out dir (T4b/CC-136). The base
    repo mount is always :ro (CC-154)."""
    evidence_dir, _ = label_paths(args.label)
    os.makedirs(evidence_dir, exist_ok=True)

    marker = os.path.join(evidence_dir, ".running")
    with open(marker, "w", encoding="utf-8") as f:
        f.write(f"{int(time.time())} {os.getpid()}\n")

    _install_signal_handlers()
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    # The container runs the IMAGE's system python (the SDK is baked in);
    # the host venv python is only for the host-side gates.
    # T4 (CC-135): the rw carve-outs come from the ticket's declared paths,
    # derived by main() with the same rule the container-side validation uses.
    name, argv = sandbox.sandbox_argv(
        REPO_ROOT, LOG_DIR, image,
        ["/usr/bin/python3", "launcher/stanok.py"] + _inner_run_argv(args),
        rw_paths=rw_paths, ro_paths=ro_paths)
    log(f"SANDBOX: docker container {name}")
    try:
        proc = subprocess.Popen(argv, start_new_session=True)
        rc = proc.wait()
    except KeyboardInterrupt:
        rc = _INTERRUPTED_RC or 130
    finally:
        sandbox.docker_stop(name)
        # CC-134: the container wrote the verdict into LOG_DIR (evidence/ is
        # read-only there); publish it to the host-owned evidence/<label> now
        # that the container is gone. BEFORE the marker removal, so the
        # supervisor never sees "not running" with the summary still missing.
        _publish_evidence(args.label)
        try:
            os.remove(marker)
        except OSError:
            pass
    return rc


def launch_background(args) -> int:
    """Background run (replaces launch.sh's nohup branch): a detached
    self-spawn executes the sync path — the child writes the marker with its
    own pid and supervises the container (or runs in-process under
    STANOK_NO_SANDBOX). The parent WAITS for the child's `.running` marker
    before returning: a return before the marker is written is a start race —
    the first `status` reports a false `missing` and a blocking wait loop
    exits early (w12-verify incident). rc=17: the child died (or stalled)
    before writing the marker — a launch failure, not a run defect.

    `--follow` (CC-140): after the marker is confirmed, block in `cmd_wait`
    until the run is terminal and print its final status — so ONE background
    Bash call carries both the launch and the verdict notification."""
    log_path = os.path.join(LOG_DIR, f"{args.label}.launch.log")
    evidence_dir, _ = label_paths(args.label)
    marker = os.path.join(evidence_dir, ".running")
    child_argv = [sys.executable, os.path.abspath(__file__)] + _inner_run_argv(args)
    with open(log_path, "a", encoding="utf-8") as lf:
        child = subprocess.Popen(child_argv, stdout=lf, stderr=subprocess.STDOUT,
                                 start_new_session=True, cwd=REPO_ROOT)
    summary = os.path.join(evidence_dir, "summary.json")
    deadline = time.monotonic() + 60
    while not os.path.exists(marker):
        if child.poll() is not None:
            # The child exited. A fast abort (rc=13/20/14) writes summary.json
            # and removes the marker BEFORE exiting — a process exit means all
            # its writes are complete, so a present summary.json is a finished
            # run, not a launch failure. No summary = the child died before
            # reaching any abort path (crash/import error) -> rc=17.
            if os.path.exists(summary):
                log(f"Background child (PID {child.pid}) exited "
                    f"rc={child.returncode} with a summary (fast abort)")
                return cmd_wait(args.label) if args.follow else 0
            log(f"ERROR: background child (PID {child.pid}) exited "
                f"rc={child.returncode} before writing the .running marker")
            return 17
        if time.monotonic() > deadline:
            log(f"ERROR: background child (PID {child.pid}) did not write the "
                f".running marker within 60s")
            return 17
        time.sleep(0.2)
    log(f"Machine launched in the background (PID {child.pid}). Log: {log_path}")
    if args.follow:
        return cmd_wait(args.label)
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

    p = argparse.ArgumentParser(prog="stanok", description="Stanok Runner")
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
    # CC-140: --follow makes the background launch block until the run is
    # terminal (implies --background). The supervisor's §3 uses it so the
    # completion notification of ONE background task is the verdict.
    r.add_argument("--follow", action="store_true")

    s = sub.add_parser("status")
    s.add_argument("label")

    w = sub.add_parser("wait")
    w.add_argument("label")
    w.add_argument("--timeout", type=int, default=WAIT_TIMEOUT_S)

    st = sub.add_parser("stop")
    st.add_argument("label")

    args = p.parse_args()

    if args.cmd == "status":
        return cmd_status(args.label)
    if args.cmd == "wait":
        return cmd_wait(args.label, args.timeout)
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

        # A stale summary.json from an earlier run of this label must not
        # survive: early_abort writes only when the file is absent, so the
        # supervisor could otherwise read a verdict from the previous run.
        _rotate_stale_summary(args.label)

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

        # W4 hygiene gate (rc=26): hidden/TEMP leftovers in src/tests/docs/scripts
        # leak into the machine's context and slip past dirty_tree_gate.
        if hidden_files_gate():
            return early_abort(26, "ERROR: hidden/TEMP files in src/tests/docs/scripts (rc=26)")

        # W6 verdict-subversion gate (rc=27): pytest config files under tests/
        # can force a failing test to rc=0 (conftest.py pytest_sessionfinish).
        if test_config_gate():
            return early_abort(27, "ERROR: pytest config files in tests/ (rc=27)")

        # W7 sandbox-config gate (rc=28): a sandbox.filesystem deny entry that
        # resolves (against the settings dir, per cli.js) to a non-existent
        # path makes bwrap EROFS-kill every Bash call in the session (CC-107).
        # The abort message carries the offending entries + fix (CC-157).
        sandbox_problems = sandbox_config_gate()
        if sandbox_problems:
            return early_abort(
                28, "ERROR: sandbox.filesystem deny entry invalid (rc=28): "
                + "; ".join(sandbox_problems))

        # R2: launch orchestration (the former launch.sh branches, in Python).
        in_container = os.environ.get("STANOK_IN_CONTAINER") == "1"
        no_sandbox = os.environ.get("STANOK_NO_SANDBOX") == "1"

        if args.background or args.follow:
            # The child re-runs these gates and takes the lock itself; the
            # parent must not hold the lock (flock would deadlock the child).
            # --follow implies background: it only makes sense as the tail of a
            # detached launch (a foreground follow would exceed the Bash tool's
            # 10-min cap on a 45-min run).
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
        # CC-106: the image digest/runner preflight no longer blocks the
        # launch path — it lives in doctor
        # (launcher/tests_harness/test_doctor.py::test_docker_image_digest_matches).
        if shutil.which("docker") is None:
            return early_abort(1, "ERROR: docker not found on PATH")
        # T4 (CC-135): the container's rw carve-outs must be fixed BEFORE
        # `docker run`, but the SessionPlan is built later, inside the
        # container — so the host derives them from the same ticket text with
        # the same parser and the same rule (declared_carveout). A header the
        # parser refuses (including a create-declared path that already exists,
        # CC-133) is rc=13 here, before any container starts.
        try:
            with open(args.ticket_path, encoding="utf-8") as f:
                declared, edit_paths, _ = parse_ticket_header(f.read())
            assert_create_paths_are_new(declared, edit_paths)
        except (OSError, ValueError) as e:
            return early_abort(13, f"ERROR: ticket parse error: {e}")
        rw_paths = host_rw_paths(declared)
        ro_paths = host_ro_paths(declared, rw_paths)
        return run_sandboxed(args, rw_paths, ro_paths)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
