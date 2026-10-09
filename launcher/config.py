"""config — the explicit runtime configuration (C, ARCHITECTURE coupling decision).

The Config dataclass replaces the hub's module-level constants: every static
setting has a DEFAULT here, so a test constructs `Config(repo_root=str(repo))`
directly; `from_env()` replicates the former hub import-time env logic verbatim
(including the turn-timeout adjustment and the LOG_DIR makedirs). RunState
carries the per-run mutable paths (evidence_dir, live_dir, marker_path,
interrupted_rc) — created by cli.cmd_run from cfg.label_paths and threaded
through session/ticket/summary explicitly. Env-at-call-time reads (the
monkeypatched runtime knobs: STANOK_IN_CONTAINER, STANOK_NO_SANDBOX,
STANOK_REQUIRED_WINDOW, STANOK_CONTAINER_*, STANOK_OPIK_URL, ...) stay env
reads in their modules — only static constants live here.
"""

import os
import shutil
from dataclasses import dataclass

LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
# If STANOK_REPO is not set, we go up one level (stanok/launcher -> stanok)
DEFAULT_REPO = os.path.abspath(os.path.join(LAUNCHER_DIR, ".."))
DEFAULT_MODEL = "qwen3.8-flash-next-iq3_xxs"

# Stage 3 (T3-4, SPEC-VERDICT-INTEGRITY §2): the worker's summary lives on
# the container's WRITABLE LAYER (not tmpfs, not a mount): it survives
# `docker stop` and dies with `docker rm`. The host retrieves it with
# `docker cp` after the container exits — the verdict is no longer built
# from a file the worker left in a mount shared with the host.
CONTAINER_SUMMARY_ROOT = "/var/tmp/stanok-evidence"


@dataclass(frozen=True)
class Config:
    """Static machine configuration — one object, passed explicitly from
    cli.main() down. Frozen: a run's config cannot drift mid-session."""
    repo_root: str = DEFAULT_REPO
    log_dir: str = "/tmp/stanok-logs"
    model: str = DEFAULT_MODEL
    server_url: str = "http://127.0.0.1:8080"
    claude_bin: str = "claude"
    default_retries: int = 2
    max_test_lines: int = 60
    max_test_bytes: int = 4096
    api_timeout_s: float = 600.0
    turn_timeout_s: float = 1800.0
    max_agent_turns: int = 60
    # Native Bash replaces the old MCP `run` tool (Docker refactor): the model
    # runs `bash scripts/run.sh {list,test,smoke}` directly; the boundary is the
    # container, not a per-command allowlist.
    curated_tools: tuple[str, ...] = ("Read", "Write", "Edit", "Glob", "Grep", "Bash")
    docker_image: str = "stanok-machine:latest"

    @classmethod
    def from_env(cls) -> "Config":
        """Build the config from the environment — the exact logic the hub ran
        at import time before C (PLAN-AUDIT: env is the operator's interface,
        the defaults are the contract)."""
        api_timeout_s = max(1.0, float(os.environ.get("STANOK_API_TIMEOUT_S", "600")))
        turn_timeout_s = float(os.environ.get("STANOK_TURN_TIMEOUT_S", "1800"))
        # The turn watchdog must outlive one full API timeout plus a margin,
        # otherwise a slow-but-live API call is killed as a silent stall.
        if turn_timeout_s <= api_timeout_s:
            turn_timeout_s = api_timeout_s + max(15.0, api_timeout_s * 0.2)
        log_dir = os.environ.get("STANOK_LOG_DIR", "/tmp/stanok-logs")
        os.makedirs(log_dir, exist_ok=True)
        return cls(
            repo_root=os.path.abspath(os.environ.get("STANOK_REPO", DEFAULT_REPO)),
            log_dir=log_dir,
            model=os.environ.get("STANOK_MODEL", DEFAULT_MODEL),
            server_url=os.environ.get("STANOK_SERVER_URL", "http://127.0.0.1:8080"),
            claude_bin=os.environ.get("STANOK_CLAUDE_BIN", shutil.which("claude") or "claude"),
            default_retries=int(os.environ.get("STANOK_LOCAL_RETRIES", "2")),
            api_timeout_s=api_timeout_s,
            turn_timeout_s=turn_timeout_s,
            # CLI --max-turns ceiling: max model calls (agentic turns) per query().
            max_agent_turns=int(os.environ.get("STANOK_MAX_AGENT_TURNS", "60")),
            docker_image=os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest"),
        )

    @property
    def api_timeout_ms(self) -> str:
        return str(int(self.api_timeout_s * 1000))

    def label_paths(self, label: str) -> tuple[str, str]:
        """(evidence_dir, live_dir) for a label.

        Host: evidence/<label> holds the verdict (summary.json) the supervisor
        reads, LOG_DIR/<label> the session jsonl + quarantine.

        Container (CC-134): evidence/ is read-only through the repo :ro mount, so
        BOTH paths resolve into the rw LOG_DIR/<label>; the host publishes the
        verdict back into evidence/<label> after the container exits
        (_publish_evidence). Routed here, so every writer —
        launcher.stdout.log, the .running marker — follows automatically.
        STANOK_IN_CONTAINER is read at CALL time (the container/host identity is
        runtime state, not config).

        T3-4: summary.json is NOT routed here anymore — the container's
        summary target is the writable-layer path, see summary_dir."""
        live = os.path.join(self.log_dir, label)
        if os.environ.get("STANOK_IN_CONTAINER") == "1":
            return (live, live)
        return (os.path.join(self.repo_root, "evidence", label), live)

    def summary_dir(self, label: str) -> str:
        """Where the process that runs the session writes summary.json (T3-4).

        Container: CONTAINER_SUMMARY_ROOT/<label> — a container-internal
        writable-layer path: it survives `docker stop` (so the host can
        `docker cp` it out) and dies with `docker rm`. The worker no longer
        shares a writable summary file with the host's LOG_DIR.
        Host / no-sandbox: the evidence dir — the host is the publisher.
        Same call-time STANOK_IN_CONTAINER routing rule as label_paths."""
        if os.environ.get("STANOK_IN_CONTAINER") == "1":
            return os.path.join(CONTAINER_SUMMARY_ROOT, label)
        return os.path.join(self.repo_root, "evidence", label)


@dataclass
class RunState:
    """Per-run mutable state, created by cli.cmd_run/run_sandboxed from
    cfg.label_paths(label) and threaded explicitly: the marker path, the live
    (LOG_DIR/<label>) dir, the evidence dir, and the signal-handler rc."""
    evidence_dir: str
    live_dir: str
    marker_path: str
    interrupted_rc: int = 0
