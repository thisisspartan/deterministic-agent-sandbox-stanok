"""Docker sandbox boundary (R2: the former sandbox-run.sh, in Python).

Single source of the `docker run` argv: mounts, env passthrough, resource
limits, hardening. The caller (cli.py run_sandboxed) runs the returned
argv as a supervised child inside a try/finally that guarantees
`docker stop` -> `docker cp` (retrieve the worker's summary from the
container's writable layer, T3-4) -> `docker rm -f` + marker cleanup on
every exit path (normal, crash, signal) — the bash reaper trap's
guarantee, now structural. The worker container runs WITHOUT `--rm`
(T3-4): it must survive its exit so the summary can be retrieved.

Transcribed 1:1 from sandbox-run.sh (deleted in R2): same volume set, same
STANOK_* env passthrough, same limits, same seccomp/apparmor unconfined
trade (required for the claude-code native bwrap sandbox inside the
container), same --network=host (loopback to the local llama-server).
"""
import os
import subprocess

# The default project zones — the ONE literal zone list (CC-132). Two
# consumers: gates.hidden_files_gate (which dirs to scan) and
# ticket.declared_carveout (a bare zone name is undeclarable). It is NOT the
# rw mount set: since T4 (CC-135) the container's rw carve-outs are derived
# per ticket from the declared paths (ticket.declared_carveout) and passed to
# sandbox_argv
# as `rw_paths`. The zones are merely the dirs hidden_files_gate watches and
# the names a declared path may not BE.
#
# CC-134 removed the former "evidence" carve-out: evidence/ is read-only in
# the container (still reachable through the repo :ro mount, so an in-container
# write is an EROFS refusal, not "not found"). The container writes the
# streaming log and the marker into the rw LOG_DIR/<label>; the verdict
# (summary.json) goes to the container's writable layer
# (config.CONTAINER_SUMMARY_ROOT, T3-4 — survives `docker stop`, dies with
# `docker rm`). The HOST retrieves it with `docker cp` after the container
# exits and publishes it into evidence/<label> (summary._publish_evidence).
WRITABLE_ZONES = ("src", "tests", "docs", "scripts")


def _mount_specs(repo_root: str, log_dir: str, rw_paths: tuple,
                 ro_paths: tuple) -> list[str]:
    """The `-v` mount set, in order (base :ro first, then the carve-outs).

    rw_paths are repo-relative paths (files or dirs) to carve out rw — the
    derivation is ticket.declared_carveout (T4, CC-135), the host computes
    them before `docker run`. ro_paths are the pre-existing contract files
    (tests/**, scripts/run.sh — ticket.host_ro_paths, T4b/CC-136) re-bound
    :ro ON TOP of a rw carve-out DIR: Docker layers a file bind over a dir
    bind by specificity, so a protected file stays immutable while new
    siblings in that dir stay creatable. Emitted after the rw binds (deeper
    destination wins).

    Writable carve-outs: base repo read-only, the ticket's declared paths
    re-mounted rw on top (Docker layers -v mounts by specificity) — the T3
    experiment (2026-09-24): an existing file bound rw over the ro repo is
    writable while its siblings stay EROFS, and a file bound ro over a rw DIR
    is EROFS while its new siblings stay creatable (verified 2026-09-24).
    .git inherits :ro from the base mount — git reads work, git writes fail
    at the filesystem layer. Parent of the repo mounted ro FIRST: tickets live
    in $PARENT_DIR/tickets and the role-leak gate (rc=24) checks
    $PARENT_DIR/CLAUDE.md.
    The base repo is ALWAYS :ro (CC-154).
    """
    parent_dir = os.path.dirname(repo_root)
    specs = [
        f"{parent_dir}:{parent_dir}:ro",
        f"{repo_root}:{repo_root}:ro",
    ]
    specs += [f"{repo_root}/{rel}:{repo_root}/{rel}:rw" for rel in rw_paths]
    specs += [f"{repo_root}/{rel}:{repo_root}/{rel}:ro" for rel in ro_paths]
    specs.append(f"{log_dir}:{log_dir}:rw")
    return specs


def _container_env(claude_tmp: str) -> dict[str, str]:
    """The `-e` env set for the container process.

    Env passthrough: stanok.py reads only STANOK_* (Prefix Invariance).
    R4: node + claude are baked into the image at /usr/local/bin — no host
    bind-mounts, PATH just needs the image dirs.
    """
    env = {k: v for k, v in os.environ.items() if k.startswith("STANOK_")}
    env["STANOK_IN_CONTAINER"] = "1"
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    env["HOME"] = "/home/stanok"
    env["CLAUDE_TMPDIR"] = claude_tmp
    # T4 baseline (CC-135): declared paths may be files inside otherwise-ro
    # dirs, so CPython must not drop __pycache__/*.pyc next to an imported
    # module. run.sh's py runner already sets this for pytest; this covers the
    # agent's own python invocations (deterministic env, not a workaround).
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for var in ("http_proxy", "https_proxy", "no_proxy", "NO_PROXY"):
        if os.environ.get(var):
            env[var] = os.environ[var]
    # Diagnostic passthrough (CC-082 T6 capture): CLI debug log file + SDK HTTP
    # logging + NODE_OPTIONS (abort()/fetch forensic preload, --require).
    # Forwarded ONLY when set on the host (opt-in per launch); logging
    # only — never alters transport behavior.
    for var in ("DEBUG_SDK", "ANTHROPIC_LOG", "CLAUDE_CODE_DEBUG_LOGS_DIR",
                "CLAUDE_CODE_DEBUG_LOG_LEVEL", "NODE_OPTIONS"):
        if os.environ.get(var):
            env[var] = os.environ[var]
    return env


def sandbox_argv(repo_root: str, log_dir: str, image: str, inner_argv: list,
                 rw_paths: tuple = (), ro_paths: tuple = ()) -> tuple:
    """Return (container_name, docker_argv).

    inner_argv is the container-side command (e.g.
    ["/usr/bin/python3", "launcher/stanok.py", "run", ...]).

    rw_paths/ro_paths are the per-ticket mount carve-outs derived by the host
    before `docker run` (ticket.declared_carveout / ticket.host_ro_paths —
    see _mount_specs). The default is () = nothing writable: a caller that
    forgets them gets a read-only container, never an open one.
    """
    uid, gid = os.getuid(), os.getgid()
    name = f"stanok-{os.path.basename(repo_root)}-{os.getpid()}"

    # The CLI's nested bwrap binds its per-uid tmp dir rw — but ONLY when the
    # path exists as the bwrap args are formed: cli.js's allowOnly loop skips
    # non-existent write paths ("Skipping non-existent write path") and
    # sandboxTmpDir = (CLAUDE_CODE_TMPDIR || "/tmp") + Na1() ("claude-<uid>")
    # is created lazily. On the FIRST Bash call of a session the bind is
    # therefore absent and the cwd-file write hits EROFS (CC-141, the
    # "Слой 2" defect). Pre-creating the dir on the HOST does not help — it is
    # not visible in the container (nothing binds /tmp). Mount a tmpfs AT that
    # exact container path instead: it exists before the CLI starts, so the
    # bind is emitted from the very first invocation. Na1() uses getuid(),
    # and `--user {uid}` makes the container uid ours — the paths agree.
    claude_tmp = f"/tmp/claude-{uid}"

    argv = [
        # T3-4: NO `--rm` — the container must survive its exit so the host
        # can retrieve the summary from its writable layer (docker cp) and
        # only then remove it (docker rm -f, run_sandboxed's finally).
        "docker", "run", "--name", name, "--init",
        # --network=host: loopback reachability to the local llama-server
        # (STANOK_SERVER_URL). No network isolation — same trust boundary as
        # the bwrap era, different mechanism.
        "--network=host",
        # Ephemeral HOME on a tmpfs: no host coupling, the CLI's ~/.claude
        # and ~/.claude.json live and die with the container.
        "--tmpfs", f"/home/stanok:uid={uid},gid={gid},mode=700",
        # The CLI's per-uid tmp dir (see above): a tmpfs, not a host bind —
        # hermetic, dies with the container, and present before bwrap forms
        # its args, which is the whole point (CC-141). `exec` matters: the
        # nested runtime exports TMPDIR=<this dir> (cli.js aG8), so a
        # tool/test writing a temp script to $TMPDIR and running it must not
        # hit docker's default noexec (upstream /tmp/claude is a plain dir).
        "--tmpfs", f"{claude_tmp}:uid={uid},gid={gid},mode=700,exec",
        "-w", repo_root,
    ]

    for spec in _mount_specs(repo_root, log_dir, rw_paths, ro_paths):
        argv += ["-v", spec]

    for k, v in _container_env(claude_tmp).items():
        argv += ["-e", f"{k}={v}"]

    # Resource limits: defense in depth alongside the Python TURN_TIMEOUT_S
    # watchdog (fork bomb, runaway build, filled disk).
    argv += [
        f"--memory={os.environ.get('STANOK_CONTAINER_MEM', '4g')}",
        f"--pids-limit={os.environ.get('STANOK_CONTAINER_PIDS', '512')}",
        f"--cpus={os.environ.get('STANOK_CONTAINER_CPUS', '2')}",
        # Hardening: cap-drop=ALL + no-new-privileges stay the effective
        # boundary; seccomp/apparmor UNCONFINED are the layer traded away so
        # the claude-code native sandbox (bwrap) can run INSIDE the container
        # (verified empirically 2026-09-18).
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--security-opt", "seccomp=unconfined",
        "--security-opt", "apparmor=unconfined",
        "--user", f"{uid}:{gid}",
        image,
    ]
    argv += inner_argv
    return name, argv


def fresh_verify_argv(repo_root: str, image: str) -> tuple:
    """Stage 3 (T3-3, SPEC-VERDICT-INTEGRITY §2): the argv of the FRESH
    verification container — the host's independent re-run of the suite in a
    container the worker never touched, after the worker's container is gone.

    Hardening is STRICTER than the worker's (sandbox_argv), because the fresh
    check runs only `bash scripts/run.sh` — no claude-code, no nested bwrap:
      - `--network=none`: the check must not reach the inference server or
        anything else (the worker's --network=host is for the model, not for
        the tests);
      - NO seccomp/apparmor `unconfined`: that trade exists only so bwrap
        can run inside the worker's container;
      - the WHOLE repo `:ro`, no rw carve-outs, no LOG_DIR bind: the check
        sees the tree exactly as the host sees it and cannot change it;
      - no STANOK_* env passthrough: the model's environment is not part of
        the verification.
    Same image, `--rm`, cap-drop=ALL + no-new-privileges, `--user`, tmpfs
    home + tmp (hermetic scratch, dies with the container), workdir = repo.

    Inner command: `bash scripts/run.sh list` then `bash scripts/run.sh test
    --all` — the same pair verify_gate runs. A `list` failure (W12: an
    unclaimed test-like file) fails the check even if the suite would pass.
    run.sh self-limits per file (rc=124); the host backstop is in
    verify.fresh_verify. Returns (container_name, docker_argv)."""
    uid, gid = os.getuid(), os.getgid()
    name = f"stanok-fresh-{os.path.basename(repo_root)}-{os.getpid()}"

    argv = [
        "docker", "run", "--rm", "--name", name, "--init",
        "--network=none",
        "--tmpfs", f"/home/stanok:uid={uid},gid={gid},mode=700",
        "--tmpfs", f"/tmp:uid={uid},gid={gid},mode=700,exec",
        "-w", repo_root,
        "-v", f"{repo_root}:{repo_root}:ro",
        "-e", "PATH=/usr/local/bin:/usr/bin:/bin",
        "-e", "HOME=/home/stanok",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        # Same resource limits as the worker (defense in depth against a
        # runaway suite in the host's fresh-check container).
        f"--memory={os.environ.get('STANOK_CONTAINER_MEM', '4g')}",
        f"--pids-limit={os.environ.get('STANOK_CONTAINER_PIDS', '512')}",
        f"--cpus={os.environ.get('STANOK_CONTAINER_CPUS', '2')}",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user", f"{uid}:{gid}",
        image,
        "bash", "-c",
        "bash scripts/run.sh list; list_rc=$?; "
        "bash scripts/run.sh test --all; test_rc=$?; "
        'if [ "$list_rc" -ne 0 ]; then exit "$list_rc"; fi; '
        'exit "$test_rc"',
    ]
    return name, argv


def docker_stop(name: str) -> None:
    """Best-effort `docker stop -t 5` — the reaper's cleanup call."""
    try:
        subprocess.run(["docker", "stop", "-t", "5", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def docker_cp(name: str, container_path: str, host_path: str) -> tuple[int, str]:
    """Stage 3 (T3-4): `docker cp name:path host_path` — retrieve the
    worker's summary from the STOPPED container's writable layer (works on a
    stopped container — verified by test_stage3_worker_lifecycle, the plan's
    stop-condition). Returns (rc, stderr): a non-zero rc is an ENV-FAIL at
    the call site — the verdict cannot be PASS without the summary it was
    built from."""
    try:
        sp = subprocess.run(["docker", "cp", f"{name}:{container_path}", host_path],
                            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return (1, str(e))
    return (sp.returncode, (sp.stderr or "").strip())


def docker_rm_force(name: str) -> None:
    """Stage 3 (T3-4): `docker rm -f` — the `--rm` replacement: the host
    removes the container only after retrieving the summary. Best-effort like
    docker_stop: a failed rm leaves a stopped container for the reaper,
    never a hang."""
    try:
        subprocess.run(["docker", "rm", "-f", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def reap_stopped(repo_root: str) -> None:
    """Stage 3 (T3-4) reaper: remove STOPPED containers of THIS repo — crash
    leftovers from earlier runs (a host killed between stop and rm). Running
    containers are NOT touched: the status filter admits only exited/created.
    Called at the start of a host run (cli.run_sandboxed), not cmd_run:
    cmd_run executes inside the container, where the docker CLI is absent.
    Best-effort: a reaper failure must not block a new run.

    Operator condition 1 (2026-10-09): the name filter is narrowed to
    `stanok-{basename(repo_root)}-` — the exact prefix sandbox_argv gives
    this repo's containers. A generic `stanok-` would reap a foreign repo's
    stopped container (another checkout, a worktree run): not our leftover.
    The trailing dash prevents substring bleed: `name=stanok-repo-` does not
    match `stanok-repoA-...` (docker's name filter is a substring match)."""
    prefix = f"stanok-{os.path.basename(repo_root)}-"
    try:
        sp = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={prefix}",
             "--filter", "status=exited", "--filter", "status=created", "-q"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return
    ids = [x for x in sp.stdout.split() if x]
    if not ids:
        return
    try:
        subprocess.run(["docker", "rm", *ids],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass
