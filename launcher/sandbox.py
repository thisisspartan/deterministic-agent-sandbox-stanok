"""Docker sandbox boundary (R2: the former sandbox-run.sh, in Python).

Single source of the `docker run` argv: mounts, env passthrough, resource
limits, hardening. The caller (stanok.py run_sandboxed) runs the returned
argv as a supervised child inside a try/finally that guarantees
`docker stop` + marker cleanup on every exit path (normal, crash, signal) —
the bash reaper trap's guarantee, now structural.

Transcribed 1:1 from sandbox-run.sh (deleted in R2): same volume set, same
STANOK_* env passthrough, same limits, same seccomp/apparmor unconfined
trade (required for the claude-code native bwrap sandbox inside the
container), same --network=host (loopback to the local llama-server).
"""
import os
import subprocess


def sandbox_argv(repo_root: str, log_dir: str, image: str, inner_argv: list) -> tuple:
    """Return (container_name, docker_argv).

    inner_argv is the container-side command (e.g.
    ["/usr/bin/python3", "launcher/stanok.py", "run", ...]).
    """
    parent_dir = os.path.dirname(repo_root)
    uid, gid = os.getuid(), os.getgid()
    name = f"stanok-{os.path.basename(repo_root)}-{os.getpid()}"

    argv = [
        "docker", "run", "--rm", "--name", name, "--init",
        # --network=host: loopback reachability to the local llama-server
        # (STANOK_SERVER_URL). No network isolation — same trust boundary as
        # the bwrap era, different mechanism.
        "--network=host",
        # Ephemeral HOME on a tmpfs: no host coupling, the CLI's ~/.claude
        # and ~/.claude.json live and die with the container.
        "--tmpfs", f"/home/stanok:uid={uid},gid={gid},mode=700",
        "-w", repo_root,
    ]

    # Writable carve-outs: base repo read-only, subpaths re-mounted rw on top
    # (Docker layers -v mounts by specificity). .git inherits :ro from the
    # base mount — git reads work, git writes fail at the filesystem layer.
    # Parent of the repo mounted ro FIRST: tickets live in $PARENT_DIR/tickets
    # and the role-leak gate (rc=24) checks $PARENT_DIR/CLAUDE.md.
    for spec in (
        f"{parent_dir}:{parent_dir}:ro",
        f"{repo_root}:{repo_root}:ro",
        f"{repo_root}/src:{repo_root}/src:rw",
        f"{repo_root}/tests:{repo_root}/tests:rw",
        f"{repo_root}/docs:{repo_root}/docs:rw",
        f"{repo_root}/scripts:{repo_root}/scripts:rw",
        f"{repo_root}/evidence:{repo_root}/evidence:rw",
        f"{log_dir}:{log_dir}:rw",
    ):
        argv += ["-v", spec]

    # Env passthrough: stanok.py reads only STANOK_* (Prefix Invariance).
    # R4: node + claude are baked into the image at /usr/local/bin — no host
    # bind-mounts, PATH just needs the image dirs.
    env = {k: v for k, v in os.environ.items() if k.startswith("STANOK_")}
    env["STANOK_IN_CONTAINER"] = "1"
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    env["HOME"] = "/home/stanok"
    for var in ("http_proxy", "https_proxy", "no_proxy", "NO_PROXY"):
        if os.environ.get(var):
            env[var] = os.environ[var]
    for k, v in env.items():
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


def docker_stop(name: str) -> None:
    """Best-effort `docker stop -t 5` — the reaper's cleanup call."""
    try:
        subprocess.run(["docker", "stop", "-t", "5", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass
