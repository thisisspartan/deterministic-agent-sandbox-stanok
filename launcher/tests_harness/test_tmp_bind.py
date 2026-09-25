"""CC-141: the CLI's per-uid tmp dir must EXIST inside the container (tmpfs).

The "Слой 2" defect (CONTEXT.md): the FIRST Bash call of every session died
with `/tmp/claude-1000/cwd-XXXX: Read-only file system`; the second call was
fine. Root cause, source-verified in cli.js 2.1.88:

  * sandboxTmpDir = (CLAUDE_CODE_TMPDIR || "/tmp") + Na1(), Na1() =
    "claude-<getuid()>"  ->  /tmp/claude-<uid>;
  * that dir IS in bwrap's allowOnly (AC() is appended to filesystem.allowWrite
    in the settings builder, and DC_() emits [...yn6(), ...allowWrite]);
  * but KC_()'s bind loop SKIPS non-existent paths ("Skipping non-existent
    write path"), and the dir is created lazily -> the first invocation emits
    no `--bind /tmp/claude-<uid>`, so the cwd-file write lands on the `--ro-bind
    / /` view -> EROFS. By the second invocation the dir exists, so it is bound.

The host-side pre-create the harness used to do was invisible: nothing binds
/tmp into the container. The fix is a `--tmpfs` AT that exact container path,
so it exists before the CLI starts and the bind is emitted from call one.

Pinned here (the e2e tests need docker; they skip cleanly without it):
  1  sandbox_argv mounts /tmp/claude-<uid> as a tmpfs (uid/gid/mode 700/exec)
  2  sandbox_argv does NOT bind the HOST /tmp dir (it must not create it)
  3  e2e: dir exists before any command, nested bwrap writes, temp script runs
  4  e2e negative control: without the tmpfs, that same bwrap write is EROFS
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import sandbox  # noqa: E402


def _argv(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    log = tmp_path / "logs"
    log.mkdir()
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    return sandbox.sandbox_argv(str(repo), str(log), image, ["true"])


# --- 1/2: the argv contract --------------------------------------------------

def test_argv_mounts_cli_tmpdir_as_tmpfs(tmp_path):
    uid = os.getuid()
    _, argv = _argv(tmp_path)
    spec = f"/tmp/claude-{uid}:uid={uid},gid={os.getgid()},mode=700,exec"
    i = argv.index("--tmpfs")
    assert spec in argv, argv
    assert argv[i + 1] == f"/home/stanok:uid={uid},gid={os.getgid()},mode=700"
    # It is the SECOND tmpfs (HOME is first) — order is not load-bearing, but
    # both must be tmpfs mounts, never `-v` host binds.
    assert argv.count("--tmpfs") == 2


def test_argv_does_not_bind_host_tmp_dir(tmp_path):
    # A `-v /tmp/claude-<uid>:...` would couple the container to the host dir
    # (and the old host-side pre-create did NOT survive into the container
    # anyway). The fix is the tmpfs, so no bind spec may target it.
    _, argv = _argv(tmp_path)
    uid = os.getuid()
    binds = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert not any(spec.startswith(f"/tmp/claude-{uid}:") for spec in binds), binds


# --- 3/4: real docker run ----------------------------------------------------

def _docker(argv, timeout=180):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    finally:
        sandbox.docker_stop(argv[argv.index("--name") + 1])


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_container_tmpdir_exists_before_any_command(tmp_path):
    d = f"/tmp/claude-{os.getuid()}"
    # `test -d` runs FIRST: the command itself never creates the dir, so it can
    # only exist because the tmpfs made it present before the CLI started.
    cmd = (
        f"test -d '{d}' && echo DIR-EXISTS; "
        f"bwrap --ro-bind / / --bind '{d}' '{d}' --dev /dev --proc /proc -- "
        f"bash -c 'touch {d}/cwd-e2e && echo BWRAP-WRITE-OK'; "
        # TMPDIR parity (cli.js aG8 exports TMPDIR=<this dir>): a temp script
        # must be runnable, i.e. the tmpfs must not be docker's default noexec.
        f"printf '#!/bin/sh\\necho EXEC-OK\\n' > '{d}/t.sh'; chmod 755 '{d}/t.sh'; '{d}/t.sh'"
    )
    # sandbox_argv rebuilds the whole tmpfs/mount set from the same helper.
    repo = tmp_path / "repo"
    repo.mkdir()
    log = tmp_path / "logs"
    log.mkdir()
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    name, argv = sandbox.sandbox_argv(str(repo), str(log), image,
                                      ["bash", "-c", cmd])
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    finally:
        sandbox.docker_stop(name)
    assert "DIR-EXISTS" in proc.stdout, proc
    assert "BWRAP-WRITE-OK" in proc.stdout, proc
    assert "EXEC-OK" in proc.stdout, proc


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_without_tmpfs_that_bwrap_write_is_erofs(tmp_path):
    # The negative control: pre-create the dir OUTSIDE bwrap (as the CLI's lazy
    # mkdir does), then `--ro-bind / /` without a bind for it -> the write hits
    # the read-only view. This is the exact string the machine reported.
    d = f"/tmp/claude-{os.getuid()}"
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    argv = [
        "docker", "run", "--rm", "--name", f"stanok-cc141-neg-{os.getpid()}",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--security-opt", "seccomp=unconfined",
        "--security-opt", "apparmor=unconfined",
        image, "bash", "-c",
        f"mkdir -p '{d}' && bwrap --ro-bind / / --dev /dev --proc /proc -- "
        f"bash -c 'touch {d}/cwd-f835'",
    ]
    proc = _docker(argv)
    assert "Read-only file system" in (proc.stdout + proc.stderr), proc
