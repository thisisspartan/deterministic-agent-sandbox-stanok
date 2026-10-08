"""cli — the CLI entry point and launch orchestration (R2).

argparse, the gate sequence in main(), cmd_run/cmd_status/cmd_wait/cmd_stop,
the sandbox supervision and the background self-spawn (--follow, CC-140).
main() builds the Config ONCE (Config.from_env) and threads it explicitly;
per-run mutable state is a RunState built from cfg.label_paths (C). `import
stanok` stays only for the logging sink (stanok._stdout_log_f) and the child
self-spawn path (stanok.__file__).
"""

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import sandbox
import stanok
from stanok import ExitCode, SessionPlan, log
from config import Config, RunState
from gates import check_test_config, dirty_tree_gate, hidden_files_gate, preflight_server, root_refusal, sandbox_config_gate, validate_label
from opik import _opik_trace_count
from session import _install_signal_handlers, run_continuous_session
from summary import _publish_evidence, _rotate_stale_summary, build_summary, write_summary
from ticket import assert_create_paths_are_new, assert_edit_paths_are_not_protected, host_ro_paths, host_rw_paths, parse_ticket_header, prepare_workspace



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


def cmd_run(cfg, args) -> int:
    try:
        if os.getpgid(0) != os.getpid():
            os.setpgid(0, 0)
    except OSError:
        pass

    evidence_dir, live_dir = cfg.label_paths(args.label)
    os.makedirs(evidence_dir, exist_ok=True)
    os.makedirs(live_dir, exist_ok=True)

    # The logging sink is a per-run handle (see the stanok module docstring):
    # opened here, assigned to the module global, released at process exit.
    stanok._stdout_log_f = open(os.path.join(evidence_dir, "launcher.stdout.log"), "a", encoding="utf-8")
    run_state = RunState(evidence_dir=evidence_dir, live_dir=live_dir,
                         marker_path=os.path.join(evidence_dir, ".running"))

    start_ts = int(time.time())
    recorded_pid = os.getpid()

    # R2: the marker is written by the host-side supervisor (run_sandboxed /
    # launch_background) with ITS pid — inside the container os.getpid() is
    # not visible from the host. If the marker already exists, preserve its
    # start_ts/pid; only a fresh in-process run (no-sandbox) writes its own.
    if os.path.exists(run_state.marker_path):
        try:
            parts = open(run_state.marker_path, "r", encoding="utf-8").read().split()
            if len(parts) >= 2:
                start_ts = int(parts[0])
                recorded_pid = int(parts[1])
        except (ValueError, OSError):
            pass

    with open(run_state.marker_path, "w", encoding="utf-8") as f:
        f.write(f"{start_ts} {recorded_pid}\n")

    _install_signal_handlers(run_state)

    job = {"label": args.label, "ticket": args.ticket}
    log(f"STANOK RUNNER | Repo: {cfg.repo_root} | Label: {args.label}")
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
        declared_paths, edit_paths, reset_none = parse_ticket_header(cfg, ticket_prompt)
        # CC-133: the create/edit split is derived from the filesystem, not
        # trusted from the header (ValueError -> rc=13 below).
        assert_create_paths_are_new(cfg, declared_paths, edit_paths)
        # CC-206: `edit:` on a protected file is an unsatisfiable contract
        # (CC-204-retry3) — refuse it here, before any workspace mutation.
        assert_edit_paths_are_not_protected(cfg, edit_paths)
    except (OSError, ValueError) as e:
        job["rc"] = int(ExitCode.TICKET)
        job["error"] = f"ticket parse error: {e}"
        write_summary(cfg, run_state, job, int(time.time()) - start_ts)
        if os.path.exists(run_state.marker_path):
            try: os.remove(run_state.marker_path)
            except OSError: pass
        return int(ExitCode.TICKET)

    if not declared_paths and not reset_none:
        job["rc"] = int(ExitCode.TICKET)
        job["error"] = ("ticket declares no `impl:`/`test:`/`docs:`/`edit:` "
                        "line and no `reset: none` — the ticket-scoped invariant "
                        "cannot be enforced (fail-closed)")
        write_summary(cfg, run_state, job, int(time.time()) - start_ts)
        if os.path.exists(run_state.marker_path):
            try: os.remove(run_state.marker_path)
            except OSError: pass
        return int(ExitCode.TICKET)
    if declared_paths:
        log(f"DECLARED PATHS: {declared_paths}")
    if edit_paths:
        log(f"EDIT-IN-PLACE PATHS (not quarantined): {edit_paths}")

    # T1 (CC-120): build the SessionPlan — the single source of file policy (I1).
    plan = SessionPlan(
        declared_paths=tuple(declared_paths),
        edit_paths=tuple(edit_paths),
    )

    if not preflight_server(cfg):
        job["rc"] = int(ExitCode.SERVER)
        job["error"] = f"Server unavailable ({cfg.server_url})"
        write_summary(cfg, run_state, job, int(time.time()) - start_ts)
        if os.path.exists(run_state.marker_path):
            try: os.remove(run_state.marker_path)
            except OSError: pass
        return int(ExitCode.SERVER)

    if prepare_workspace(cfg, run_state, plan) != 0:
        job["rc"] = int(ExitCode.WORKSPACE)
        job["error"] = "workspace prep error"
        write_summary(cfg, run_state, job, int(time.time()) - start_ts)
        if os.path.exists(run_state.marker_path):
            try: os.remove(run_state.marker_path)
            except OSError: pass
        return int(ExitCode.WORKSPACE)

    rc = 1
    try:
        rc = asyncio.run(run_continuous_session(cfg, run_state, job, ticket_prompt, args.local_retries, plan))
    except KeyboardInterrupt:
        rc = run_state.interrupted_rc or 130
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
        write_summary(cfg, run_state, job, int(time.time()) - start_ts)
        if os.path.exists(run_state.marker_path):
            try:
                os.remove(run_state.marker_path)
            except OSError:
                pass

    log(f"RUN FINISHED: rc={rc}")
    return rc


# ==================================================================================
# Control utilities (status, stop)
# ==================================================================================
def _status_dict(cfg, label: str) -> dict:
    """The status JSON `status` prints — single source, also used by `wait`.

    Precedence: a live `.running` marker (running/dead) over a summary.json
    (done) over missing. `run_sandboxed` publishes the verdict BEFORE removing
    the marker, so the marker's disappearance implies a readable summary.
    """
    evidence_dir, _ = cfg.label_paths(label)
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


def cmd_status(cfg, label: str) -> int:
    print(json.dumps(_status_dict(cfg, label)))
    return 0


WAIT_POLL_S = 5
WAIT_TIMEOUT_S = 2700  # 45 min — the cap §3 of CLAUDE.supervisor.md names


def cmd_wait(cfg, label: str, timeout_s: int = WAIT_TIMEOUT_S) -> int:
    """Block until the run reaches a terminal state, print its final status.

    This is the ONE primitive behind `run --follow` and the standalone
    `wait` subcommand (CC-140). It exists because the supervisor's
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
        st = _status_dict(cfg, label)
        if st.get("state") != "running":
            print(json.dumps(st))
            return 0
        if time.monotonic() >= deadline:
            print(json.dumps({"state": "timeout", "elapsed_s": st.get("elapsed_s")}))
            return 124
        time.sleep(WAIT_POLL_S)


def cmd_stop(cfg, label: str) -> int:
    evidence_dir, _ = cfg.label_paths(label)
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
def _inner_run_argv(cfg, args) -> list:
    """The container-side / child-side `run` argv (single source)."""
    inner = ["run", args.ticket]
    if args.direct:
        inner.append("--direct")
    if args.local_retries != cfg.default_retries:
        inner += ["--local-retries", str(args.local_retries)]
    inner += ["--", args.label, *args.extra]
    return inner


def run_sandboxed(cfg, args, rw_paths: tuple, ro_paths: tuple) -> int:
    """Host-side sync run: supervise the Docker container (replaces
    sandbox-run.sh). The marker carries THIS process's pid — cmd_stop's
    killpg lands here, and the try/finally stops the container and removes
    the marker on every exit path (normal return, crash, signal).

    rw_paths are the per-ticket rw carve-outs (T4/CC-135, derived in main()
    from the same ticket text the container will parse); ro_paths are the
    protected files re-bound :ro over a carve-out dir (T4b/CC-136). The base
    repo mount is always :ro (CC-154)."""
    evidence_dir, live_dir = cfg.label_paths(args.label)
    os.makedirs(evidence_dir, exist_ok=True)

    run_state = RunState(evidence_dir=evidence_dir, live_dir=live_dir,
                         marker_path=os.path.join(evidence_dir, ".running"))
    marker = run_state.marker_path
    with open(marker, "w", encoding="utf-8") as f:
        f.write(f"{int(time.time())} {os.getpid()}\n")

    # Isolate this process into its own group BEFORE installing the
    # handlers: the handler's killpg(0) must hit this run's group, not
    # the caller's (same guard as cmd_run).
    try:
        if os.getpgid(0) != os.getpid():
            os.setpgid(0, 0)
    except OSError:
        pass

    _install_signal_handlers(run_state)
    image = cfg.docker_image
    # The container runs the IMAGE's system python (the SDK is baked in);
    # the host venv python is only for the host-side gates.
    # T4 (CC-135): the rw carve-outs come from the ticket's declared paths,
    # derived by main() with the same rule the container-side validation uses.
    name, argv = sandbox.sandbox_argv(
        cfg.repo_root, cfg.log_dir, image,
        ["/usr/bin/python3", "launcher/stanok.py"] + _inner_run_argv(cfg, args),
        rw_paths=rw_paths, ro_paths=ro_paths)
    log(f"SANDBOX: docker container {name}")
    rc = 1  # bound before the try: a Popen failure must not NameError the finally
    try:
        proc = subprocess.Popen(argv, start_new_session=True)
        rc = proc.wait()
    except KeyboardInterrupt:
        rc = run_state.interrupted_rc or 130
    finally:
        sandbox.docker_stop(name)
        # CC-134: the container wrote the verdict into LOG_DIR (evidence/ is
        # read-only there); publish it to the host-owned evidence/<label> now
        # that the container is gone. BEFORE the marker removal, so the
        # supervisor never sees "not running" with the summary still missing.
        _publish_evidence(cfg, args.label, rc)
        try:
            os.remove(marker)
        except OSError:
            pass
    return rc


def launch_background(cfg, args) -> int:
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
    log_path = os.path.join(cfg.log_dir, f"{args.label}.launch.log")
    evidence_dir, _ = cfg.label_paths(args.label)
    marker = os.path.join(evidence_dir, ".running")
    child_argv = [sys.executable, os.path.abspath(stanok.__file__)] + _inner_run_argv(cfg, args)
    with open(log_path, "a", encoding="utf-8") as lf:
        child = subprocess.Popen(child_argv, stdout=lf, stderr=subprocess.STDOUT,
                                 start_new_session=True, cwd=cfg.repo_root)
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
                return cmd_wait(cfg, args.label)
            log(f"ERROR: background child (PID {child.pid}) exited "
                f"rc={child.returncode} before writing the .running marker")
            return int(ExitCode.CHILD_DIED)
        if time.monotonic() > deadline:
            log(f"ERROR: background child (PID {child.pid}) did not write the "
                f".running marker within 60s")
            return int(ExitCode.CHILD_DIED)
        time.sleep(0.2)
    log(f"Machine launched in the background (PID {child.pid}). Log: {log_path}")
    return cmd_wait(cfg, args.label)


# ==================================================================================
# CLI entry point
# ==================================================================================
def _resolve_ticket(cfg, arg: str, direct: bool = False) -> str:
    if direct:
        candidates = [os.path.join(cfg.repo_root, arg), os.path.abspath(arg)]
    else:
        candidates = [
            os.path.join(os.path.dirname(cfg.repo_root), arg),  # project root (highest priority)
            os.path.join(cfg.repo_root, arg),                    # machine root
            os.path.abspath(arg)                             # as given
        ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[0]


def main() -> int:
    root_refusal()
    cfg = Config.from_env()

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
    r.add_argument("--local-retries", type=int, default=cfg.default_retries)
    # CC-140/BL-1: --follow is the SOLE background flag: a detached
    # self-spawn, then block in cmd_wait until the run is terminal and print
    # its final status — so ONE background Bash call carries both the launch
    # and the verdict notification (the supervisor's §3). A bare `run` is a
    # foreground sync run.
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
        return cmd_status(cfg, args.label)
    if args.cmd == "wait":
        return cmd_wait(cfg, args.label, args.timeout)
    if args.cmd == "stop":
        return cmd_stop(cfg, args.label)

    if args.cmd == "run":
        evidence_dir, _ = cfg.label_paths(args.label)
        marker = os.path.join(evidence_dir, ".running")

        def abort(code: ExitCode, err_msg: str) -> int:
            log(err_msg)
            if os.path.exists(marker):
                # A live run's marker must survive an early abort of a
                # concurrent launch attempt: remove it only when the
                # recorded process is dead (or the marker is unparseable).
                live = False
                try:
                    with open(marker, encoding="utf-8") as f:
                        pid = int(f.read().split()[-1])
                    live = _pid_alive(pid)
                except (OSError, ValueError):
                    pass
                if not live:
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
                    "rc": int(code),
                    "verifier": "FAIL",
                    "probe_result": "EARLY-ABORT",
                    "turns": 0,
                    "error": err_msg,
                }
                with open(sum_path, "w", encoding="utf-8") as f:
                    json.dump(build_summary(cfg, job, 0), f, ensure_ascii=False, indent=2)
            return int(code)

        if validate_label(args.label):
            return abort(ExitCode.BAD_LABEL, f"ERROR: Invalid label {args.label}")

        # A stale summary.json from an earlier run of this label must not
        # survive: abort writes only when the file is absent, so the
        # supervisor could otherwise read a verdict from the previous run.
        _rotate_stale_summary(cfg, args.label)

        # ROLE-LEAK (rc=24): a parent CLAUDE.md above the repo would be auto-loaded
        # into the machine session (cwd = REPO_ROOT) -> role leak. Fail-closed before
        # reset/lock/preflight, no side effects.
        parent_claude = os.path.join(os.path.dirname(cfg.repo_root), "CLAUDE.md")
        if os.path.isfile(parent_claude):
            return abort(ExitCode.ROLE_LEAK, f"ERROR: ROLE-LEAK: parent CLAUDE.md above the repo: {parent_claude}")

        args.ticket_path = _resolve_ticket(cfg, args.ticket, direct=args.direct)
        if not os.path.isfile(args.ticket_path):
            return abort(ExitCode.TICKET, f"ERROR: Ticket not found: {args.ticket_path}")

        if dirty_tree_gate(cfg):
            return abort(ExitCode.DIRTY_TREE, "ERROR: the machine repo contains uncommitted changes (rc=22)")

        # W4 hygiene gate (rc=26): hidden/TEMP leftovers in src/tests/docs/scripts
        # leak into the machine's context and slip past dirty_tree_gate.
        if hidden_files_gate(cfg):
            return abort(ExitCode.HIDDEN_FILES, "ERROR: hidden/TEMP files in src/tests/docs/scripts (rc=26)")

        # W6 verdict-subversion gate (rc=27): pytest config files under tests/
        # can force a failing test to rc=0 (conftest.py pytest_sessionfinish).
        if check_test_config(cfg):
            return abort(ExitCode.TEST_CONFIG, "ERROR: pytest config files in tests/ (rc=27)")

        # W7 sandbox-config gate (rc=28): a sandbox.filesystem deny entry that
        # resolves (against the settings dir, per cli.js) to a non-existent
        # path makes bwrap EROFS-kill every Bash call in the session (CC-107).
        # The abort message carries the offending entries + fix (CC-157).
        sandbox_problems = sandbox_config_gate(cfg)
        if sandbox_problems:
            return abort(
                ExitCode.SANDBOX_CONFIG, "ERROR: sandbox.filesystem deny entry invalid (rc=28): "
                + "; ".join(sandbox_problems))

        # R2: launch orchestration (the former launch.sh branches, in Python).
        in_container = os.environ.get("STANOK_IN_CONTAINER") == "1"
        no_sandbox = os.environ.get("STANOK_NO_SANDBOX") == "1"

        if args.follow:
            # The child re-runs these gates and takes the lock itself; the
            # parent must not hold the lock (flock would deadlock the child).
            # --follow is the sole background form: a detached launch that
            # blocks until terminal (a foreground follow would exceed the
            # Bash tool's 10-min cap on a 45-min run).
            return launch_background(cfg, args)

        if in_container or no_sandbox:
            # In-process session (container-side Runner, or host no-sandbox):
            # the lock serializes runs of this repo.
            lock_path = os.path.join(cfg.log_dir, f"stanok-{hashlib.md5(cfg.repo_root.encode()).hexdigest()[:12]}.lock")
            lf = open(lock_path, "w")
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return abort(ExitCode.LOCK, f"LOCK: the repo is already busy with another run ({lock_path})")
            return cmd_run(cfg, args)

        # Host sync: supervise the Docker container (launcher/sandbox.py).
        # The container-side Runner re-runs the gates and takes the lock.
        # CC-106: the image digest/runner preflight no longer blocks the
        # launch path — it lives in doctor
        # (launcher/tests_harness/test_doctor.py::test_docker_image_digest_matches).
        if shutil.which("docker") is None:
            return abort(ExitCode.DEFECT, "ERROR: docker not found on PATH")
        # T4 (CC-135): the container's rw carve-outs must be fixed BEFORE
        # `docker run`, but the SessionPlan is built later, inside the
        # container — so the host derives them from the same ticket text with
        # the same parser and the same rule (declared_carveout). A header the
        # parser refuses (including a create-declared path that already exists,
        # CC-133) is rc=13 here, before any container starts.
        try:
            with open(args.ticket_path, encoding="utf-8") as f:
                declared, edit_paths, _ = parse_ticket_header(cfg, f.read())
            assert_create_paths_are_new(cfg, declared, edit_paths)
            # CC-206: same gate as cmd_run — the host must not start a
            # container for a ticket that edits a protected file.
            assert_edit_paths_are_not_protected(cfg, edit_paths)
        except (OSError, ValueError) as e:
            return abort(ExitCode.TICKET, f"ERROR: ticket parse error: {e}")
        rw_paths = host_rw_paths(cfg, declared)
        ro_paths = host_ro_paths(cfg, rw_paths)
        return run_sandboxed(cfg, args, rw_paths, ro_paths)

    return 0
