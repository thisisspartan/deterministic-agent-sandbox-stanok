"""Stage 3 T3-3 — fresh verification: the host re-runs the suite in a NEW
container the worker never touched (SPEC-VERDICT-INTEGRITY §2).

`sandbox.fresh_verify_argv(repo_root, image)` -> (name, docker_argv):
same image, `--rm`, `--network=none`, `--cap-drop=ALL` +
`no-new-privileges`, NO seccomp/apparmor `unconfined` (the fresh check runs
only `bash scripts/run.sh` — no claude-code, no nested bwrap, so the
worker's unconfined trade is not needed here), `--user uid:gid`, the WHOLE
repo `:ro` with NO rw carve-outs (the check sees the tree exactly as the
host sees it and cannot change it), tmpfs home + tmp, workdir = repo, inner
command `bash scripts/run.sh list` then `bash scripts/run.sh test --all`
(the same pair verify_gate uses; a `list` failure fails the check even if
the suite would pass — W12 semantics).

`verify.fresh_verify(cfg)` -> (rc, tail): runs it, returns the exit code
and the compressed output tail — the host's independent verdict input,
consumed by the T3-6 wiring.

Tests 1-3: argv shape (pure function, no docker).
Tests 4-5: real `docker run` (skipped when docker is absent):
  4: a host-side tree change IS visible to the fresh check (passing test ->
     rc 0; the test broken after -> rc != 0), and the check leaves the tree
     byte-identical (the manifest before == after);
  5: a network request from the fresh container fails (--network=none).
"""
import os
import shutil
import subprocess

import pytest

from launcher import sandbox, verify
from launcher.config import Config

from conftest import PY_FAIL, PY_PASS, repo, write  # noqa: F401

IMAGE = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")


def _mounts(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]


# --- 1-3: argv shape ------------------------------------------------------------

def test_fresh_argv_is_network_isolated_and_hardened(tmp_path):
    name, argv = sandbox.fresh_verify_argv(str(tmp_path / "repo"), "img")
    assert name.startswith("stanok-")  # the T3-4 reaper prefix
    assert "--rm" in argv
    assert "--network=none" in argv
    assert "--network=host" not in argv
    # no unconfined seccomp/apparmor: the fresh check does not run bwrap
    assert not [a for a in argv if "unconfined" in a]
    assert "--cap-drop=ALL" in argv
    assert "--security-opt=no-new-privileges" in argv
    assert "--user" in argv


def test_fresh_argv_mounts_the_whole_repo_read_only(tmp_path):
    root = str(tmp_path / "repo")
    _, argv = sandbox.fresh_verify_argv(root, "img")
    mounts = _mounts(argv)
    assert f"{root}:{root}:ro" in mounts
    # NO rw mount anywhere — the check cannot change the tree it judges
    assert not [m for m in mounts if m.endswith(":rw")]
    # no LOG_DIR bind: the fresh check shares nothing with the worker's dirs
    assert not [m for m in mounts if "logs" in m]
    # hermetic scratch: tmpfs home + tmp, workdir = repo
    tmpfs = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
    assert any(t.startswith("/home/stanok") for t in tmpfs)
    assert any(t.startswith("/tmp") for t in tmpfs)
    assert argv[argv.index("-w") + 1] == root


def test_fresh_argv_runs_list_then_test_all(tmp_path):
    _, argv = sandbox.fresh_verify_argv(str(tmp_path / "repo"), "img")
    inner = " ".join(argv[argv.index("img") + 1:])
    assert "scripts/run.sh list" in inner
    assert "scripts/run.sh test --all" in inner


# --- 4-5: real docker run ---------------------------------------------------------

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_fresh_check_sees_host_tree_change_and_leaves_tree_untouched(repo):
    write(repo / "tests" / "a_test.py", PY_PASS)
    cfg = Config(repo_root=str(repo))

    before = verify._tests_manifest(cfg)
    rc, tail = verify.fresh_verify(cfg)
    assert rc == 0, tail
    # the check left the tree byte-identical (whole repo :ro, no writes)
    assert verify._tests_manifest(cfg) == before

    # the host changes the tree -> the fresh check sees it (rc != 0)
    write(repo / "tests" / "a_test.py", PY_FAIL)
    rc, tail = verify.fresh_verify(cfg)
    assert rc != 0
    assert "1 == 2" in tail, tail
    assert (repo / "tests" / "a_test.py").read_text(encoding="utf-8") == PY_FAIL


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_fresh_container_has_no_network(tmp_path):
    root = str(tmp_path / "repo")
    name, argv = sandbox.fresh_verify_argv(root, IMAGE)
    # replace the inner command with a network probe (same container config)
    probe = ["python3", "-c",
             "import socket; socket.create_connection(('192.0.2.1', 80), timeout=5)"]
    cut = argv.index(IMAGE) + 1
    try:
        proc = subprocess.run(argv[:cut] + probe, capture_output=True,
                              text=True, timeout=120)
    finally:
        sandbox.docker_stop(name)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    # it is the network that is gone, not the interpreter
    assert "unreachable" in (proc.stderr + proc.stdout).lower(), proc.stderr
