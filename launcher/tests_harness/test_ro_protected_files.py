"""CC-136 (T4b): pre-existing contract files are immutable at the FS layer.

CC-135 derives the rw carve-outs from the declared paths, but an ABSENT
declared path can only be carved out through its parent DIRECTORY — so
`test: tests/new_test.py` made all of `tests/` rw, and with it every
pre-existing reference test. The audit's §2 boundary table lists the native
equivalent as ":ro bind of pre-existing test files + :rw bind of declared
paths"; this file pins the first half.

`host_ro_paths` re-binds the protected files (the SAME list the contract_lock
manifest hashes — `_protected_files`) :ro on top of a rw carve-out dir. Docker
layers a file bind over a dir bind by specificity, so:
  - a pre-existing test cannot be rewritten (EROFS, before any hook),
  - a new sibling test is still creatable,
  - CC-206: EVERY protected file under a carve-out is always :ro-bound — the
    former "`edit:`-declared files stay writable" loophole is gone; `edit:` on
    a protected path is refused by the gate (rc=13) before the container
    starts, so a declared path is never protected,
  - a protected file outside every carve-out needs no bind (the repo `:ro`
    mount already covers it).

Hardlink facts (CC-206, measured 2026-10-07 — corrects the REVIEW §4.1
assumption; pinned by the two docker tests below):
  - the machine CANNOT create the escape: `link(2)` does not cross a mount
    boundary (EXDEV), and a symlink write follows to the :ro mount (EROFS);
  - the residual is only a hardlink that PRE-EXISTS on the host in a writable
    zone: the :ro bind makes the mount point read-only, not the inode, so
    writing through it mutates the protected file. Prevention is impossible
    without a directory-level :ro (which would kill the TDD pipeline), so the
    residual is closed by DETECTION: the contract_lock manifest sees the
    changed digest and fails the run closed.

The last tests are the real `docker run` e2e the audit asked of T5.
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
import stanok  # noqa: E402

from conftest import repo, write  # noqa: E402,F401


def _host_repo(tmp_path, monkeypatch, tests=("old_test.py",), runsh=True):
    root = tmp_path / "repo"
    for rel in tests:
        write(root / "tests" / rel, "def test_x():\n    assert 1\n")
    if runsh:
        write(root / "scripts" / "run.sh", "#!/usr/bin/env bash\nexit 0\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(root))
    return root


# --- the protected list: one source ---------------------------------------------

def test_protected_files_are_tests_runsh_and_stacks(repo, monkeypatch):
    write(repo / "tests" / "a_test.py", "def test_a():\n    assert 1\n")
    write(repo / "tests" / "sub" / "b_test.py", "def test_b():\n    assert 1\n")
    write(repo / "tests" / "__pycache__" / "a_test.cpython-313.pyc", "junk")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    protected = stanok._protected_files()
    # B1 (PLAN-AUDIT-2026-10-08): the stacks manifests are contract files too
    # (run.sh derives its registry from them) — see test_stacks_protected.py.
    assert set(protected) == {"tests/a_test.py", "tests/sub/b_test.py",
                              "scripts/run.sh",
                              "scripts/stacks/jq.toml", "scripts/stacks/js.toml",
                              "scripts/stacks/py.toml"}
    # The manifest and the :ro list are the same rule, not two policy lists.
    assert set(stanok._tests_manifest()) == set(protected)


def test_protected_list_without_a_runsh(repo, monkeypatch):
    # Bootstrap: a missing scripts/run.sh is not protected (it may be created).
    # The stacks manifests are pre-existing infrastructure — protected anyway.
    write(repo / "tests" / "a_test.py", "def test_a():\n    assert 1\n")
    (repo / "scripts" / "run.sh").unlink()
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok._protected_files() == [
        "tests/a_test.py",
        "scripts/stacks/jq.toml", "scripts/stacks/js.toml",
        "scripts/stacks/py.toml"]


# --- host_ro_paths --------------------------------------------------------------

def test_no_bind_when_nothing_is_under_a_carve_out(tmp_path, monkeypatch):
    _host_repo(tmp_path, monkeypatch)
    assert stanok.host_ro_paths(("src",)) == ()


def test_protected_files_under_a_dir_carve_out_are_bound(tmp_path, monkeypatch):
    root = _host_repo(tmp_path, monkeypatch, tests=("old_test.py", "also_test.py"))
    declared, _, _ = stanok.parse_ticket_header("test: tests/new_test.py\n")
    rw = stanok.host_rw_paths(declared)
    assert rw == ("tests",)                      # absent path -> its parent dir
    ro = stanok.host_ro_paths(rw)
    assert set(ro) == {"tests/old_test.py", "tests/also_test.py"}
    # CC-206: EVERY protected file under a carve-out is :ro-bound,
    # unconditionally — nothing under a rw mount stays writable by accident.
    # (scripts/run.sh is not under one here — the repo :ro mount already
    # covers it.)
    for rel in stanok._protected_files():
        if any(rel == c or rel.startswith(c + "/") for c in rw):
            assert rel in ro, rel


def test_declared_protected_path_is_still_bound(tmp_path, monkeypatch):
    # CC-206: the `if rel in declared_set: continue` loophole is gone. A
    # protected file is bound :ro even when it appears in the declared list —
    # such a ticket is refused by the gate (rc=13) before the container
    # starts, so this call is defense-in-depth: the mount layer never trusts
    # the declaration.
    _host_repo(tmp_path, monkeypatch, tests=("old_test.py", "other_test.py"))
    declared, edits, _ = stanok.parse_ticket_header(
        "edit: tests/old_test.py\n"
        "test: tests/new_test.py\n"
    )
    assert edits == ["tests/old_test.py"]
    rw = stanok.host_rw_paths(declared)
    ro = stanok.host_ro_paths(rw)
    assert "tests/old_test.py" in ro
    assert set(ro) == {"tests/old_test.py", "tests/other_test.py"}


def test_runsh_is_bound_only_when_scripts_is_carved_out(tmp_path, monkeypatch):
    _host_repo(tmp_path, monkeypatch)
    assert "scripts/run.sh" not in stanok.host_ro_paths(("tests",))
    # scripts/ becomes a carve-out only via an absent declared path under it.
    declared = ["scripts/new_helper.sh"]
    rw = stanok.host_rw_paths(declared)
    assert rw == ("scripts",)
    assert stanok.host_ro_paths(rw) == ("scripts/run.sh",)


# --- the argv -------------------------------------------------------------------

def test_sandbox_argv_emits_the_ro_bind_after_the_rw_bind(tmp_path):
    repo_dir = tmp_path / "repo"
    for rel in ("tests", "logs"):
        (repo_dir / rel).mkdir(parents=True)
    (repo_dir / "tests" / "old_test.py").write_text("x\n", encoding="utf-8")
    _, argv = sandbox.sandbox_argv(
        str(repo_dir), str(tmp_path / "logs"), "img", ["true"],
        rw_paths=("tests",), ro_paths=("tests/old_test.py",))
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    rw = [m for m in mounts if m.endswith(":rw")]
    ro = [m for m in mounts if m.endswith(":ro")]
    assert f"{repo_dir}/tests:{repo_dir}/tests:rw" in rw
    assert f"{repo_dir}/tests/old_test.py:{repo_dir}/tests/old_test.py:ro" in ro
    # The protected bind comes AFTER the carve-out it overrides.
    assert mounts.index(f"{repo_dir}/tests/old_test.py:{repo_dir}/tests/old_test.py:ro") \
        > mounts.index(f"{repo_dir}/tests:{repo_dir}/tests:rw")

    _, argv = sandbox.sandbox_argv(str(repo_dir), str(tmp_path / "logs"), "img",
                                   ["true"], rw_paths=("tests",))
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    # default ro_paths=() -> no protected file is bound at all
    assert not [m for m in mounts if "old_test.py" in m]


# --- real docker run: the T5 e2e, at the fs layer -------------------------------

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_pre_existing_test_is_erofs_new_sibling_creatable(tmp_path, monkeypatch):
    root = _host_repo(tmp_path, monkeypatch, tests=("old_test.py",))
    log = tmp_path / "logs"
    log.mkdir()
    declared, _, _ = stanok.parse_ticket_header("test: tests/new_test.py\n")
    rw = stanok.host_rw_paths(declared)
    ro = stanok.host_ro_paths(rw)
    assert rw == ("tests",) and ro == ("tests/old_test.py",)

    cmd = (
        f"if (echo x >> '{root}/tests/old_test.py') 2>/dev/null; "
        f"then echo OLD-WRITTEN; else echo OLD-DENIED; fi; "
        f"touch '{root}/tests/new_test.py' && echo NEW-OK"
    )
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    name, argv = sandbox.sandbox_argv(str(root), str(log), image,
                                      ["bash", "-c", cmd],
                                      rw_paths=rw, ro_paths=ro)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    finally:
        sandbox.docker_stop(name)
    assert "OLD-DENIED" in proc.stdout, proc
    assert "NEW-OK" in proc.stdout, proc
    # The host copy is untouched (the mount refused the write, it did not
    # redirect it) and the new test exists only where the ticket asked.
    assert (root / "tests" / "old_test.py").read_text(encoding="utf-8") \
        == "def test_x():\n    assert 1\n"
    assert (root / "tests" / "new_test.py").is_file()


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_hardlink_escape_is_closed_by_the_mount_topology(tmp_path, monkeypatch):
    """CC-206 (measured 2026-10-07, corrects the REVIEW §4.1 assumption):
    the machine CANNOT create the hardlink escape inside the container.
    `link(2)` does not cross a mount boundary — the protected file lives on
    its own :ro bind, every carve-out is a separate mount, so linking it into
    any rw zone fails with EXDEV ("Invalid cross-device link"), and linking
    within the same tests/ mount fails for the same reason. A symlink is
    closed too: open() follows it to the :ro mount point -> EROFS.
    Prevention is therefore STRUCTURAL, not a residual to police.
    """
    root = _host_repo(tmp_path, monkeypatch, tests=("old_test.py",))
    (root / "src").mkdir()
    log = tmp_path / "logs"
    log.mkdir()
    declared, _, _ = stanok.parse_ticket_header(
        "test: tests/new_test.py\nimpl: src/new.py\n"
    )
    rw = stanok.host_rw_paths(declared)
    ro = stanok.host_ro_paths(rw)
    assert set(rw) == {"tests", "src"} and ro == ("tests/old_test.py",)

    cmd = (
        f"ln '{root}/tests/old_test.py' '{root}/tests/hard.py' 2>&1 "
        f"&& echo HARDLINK-SAME-DIR-OK || echo HARDLINK-SAME-DIR-EXDEV; "
        f"ln '{root}/tests/old_test.py' '{root}/src/hard.py' 2>&1 "
        f"&& echo HARDLINK-CROSS-ZONE-OK || echo HARDLINK-CROSS-ZONE-EXDEV; "
        f"ln -s '{root}/tests/old_test.py' '{root}/src/sym.py' && "
        f"(echo x >> '{root}/src/sym.py') 2>/dev/null "
        f"&& echo SYMLINK-WRITTEN || echo SYMLINK-DENIED"
    )
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    name, argv = sandbox.sandbox_argv(str(root), str(log), image,
                                      ["bash", "-c", cmd],
                                      rw_paths=rw, ro_paths=ro)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    finally:
        sandbox.docker_stop(name)
    assert "HARDLINK-SAME-DIR-EXDEV" in proc.stdout, proc
    assert "HARDLINK-CROSS-ZONE-EXDEV" in proc.stdout, proc
    assert "SYMLINK-DENIED" in proc.stdout, proc
    # Nothing was created, nothing changed.
    assert not (root / "src" / "hard.py").exists()
    assert (root / "tests" / "old_test.py").read_text(encoding="utf-8") \
        == "def test_x():\n    assert 1\n"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_host_hardlink_escapes_ro_bind_contract_lock_detects(tmp_path, monkeypatch):
    """CC-206 residual, pinned as a fact: the escape exists only for a
    hardlink that PRE-EXISTS on the host (created before the run, outside the
    container) in a writable zone — e.g. `src/hard.py` linked to
    `tests/old_test.py`. The :ro bind makes the mount point read-only, not
    the inode: writing through the host-made hardlink mutates the protected
    file. Prevention is impossible without a directory-level :ro (which would
    kill the TDD pipeline), so the residual is closed by DETECTION: the
    contract_lock manifest sees the changed digest and fails the run closed.
    """
    root = _host_repo(tmp_path, monkeypatch, tests=("old_test.py",))
    (root / "src").mkdir()
    os.link(str(root / "tests" / "old_test.py"), str(root / "src" / "hard.py"))
    log = tmp_path / "logs"
    log.mkdir()
    declared, _, _ = stanok.parse_ticket_header("impl: src/new.py\n")
    rw = stanok.host_rw_paths(declared)
    ro = stanok.host_ro_paths(rw)
    assert rw == ("src",) and ro == ()  # old_test.py: repo :ro mount covers it

    before = stanok._tests_manifest()
    assert "tests/old_test.py" in before

    cmd = f"(echo x >> '{root}/src/hard.py') 2>/dev/null " \
          f"&& echo HARDLINK-WRITTEN || echo HARDLINK-DENIED"
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    name, argv = sandbox.sandbox_argv(str(root), str(log), image,
                                      ["bash", "-c", cmd],
                                      rw_paths=rw, ro_paths=ro)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    finally:
        sandbox.docker_stop(name)
    # The write through the shared inode SUCCEEDS (the residual is real).
    assert "HARDLINK-WRITTEN" in proc.stdout, proc

    # Host-side: the protected file's CONTENT changed through the shared inode.
    changed = (root / "tests" / "old_test.py").read_text(encoding="utf-8")
    assert changed == "def test_x():\n    assert 1\nx\n", changed

    # Detection echelon: the post-turn manifest diff records the violation and
    # the forced-fail turns it into a failed run (rc=1, verifier FAIL).
    plan = stanok.SessionPlan(declared_paths=(), edit_paths=())
    job: dict = {}
    stanok._check_contract_lock(before, job, 1, plan)
    assert job["contract_lock_violations"] == ["turn 1: MODIFIED: tests/old_test.py"]
    assert stanok._contract_lock_forced_fail(job, 1) == 1
    assert job["verifier"] == "FAIL"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_stack_manifest_is_erofs_under_a_scripts_carve_out(repo, tmp_path,
                                                           monkeypatch):
    """B1 (PLAN-AUDIT-2026-10-08), the FS echelon: a ticket declaring
    `impl: scripts/probe.sh` makes scripts/ a rw carve-out — the stacks
    manifests under it must be re-bound :ro, so the machine cannot swap
    test_runner for `true` at the filesystem layer (the Python-level lock in
    test_stacks_protected.py proves detection; this proves prevention).
    The conftest `repo` fixture installs the live run.sh + scripts/stacks
    (CC-168), so this drives the real manifests."""
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    declared, _, _ = stanok.parse_ticket_header("impl: scripts/probe.sh\n")
    rw = stanok.host_rw_paths(declared)
    assert rw == ("scripts",)
    ro = stanok.host_ro_paths(rw)
    assert set(ro) == {"scripts/run.sh",
                       "scripts/stacks/jq.toml", "scripts/stacks/js.toml",
                       "scripts/stacks/py.toml"}

    cmd = (
        f"if (echo '# x' >> '{repo}/scripts/stacks/py.toml') 2>/dev/null; "
        f"then echo PYTOML-WRITTEN; else echo PYTOML-DENIED; fi; "
        f"touch '{repo}/scripts/probe.sh' && echo PROBE-OK"
    )
    # `repo` IS tmp_path (the fixture returns it) — keep logs a sibling,
    # unique per test, like the other docker tests keep it under tmp_path.
    log = tmp_path.parent / f"{tmp_path.name}-logs"
    log.mkdir()
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    name, argv = sandbox.sandbox_argv(str(repo), str(log), image,
                                      ["bash", "-c", cmd],
                                      rw_paths=rw, ro_paths=ro)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    finally:
        sandbox.docker_stop(name)
    assert "PYTOML-DENIED" in proc.stdout, proc
    assert "PROBE-OK" in proc.stdout, proc
    # The host manifest is untouched (the mount refused the write) and the
    # declared path was creatable — the carve-out itself still works.
    assert "# x" not in (repo / "scripts" / "stacks" / "py.toml").read_text(
        encoding="utf-8")
    assert (repo / "scripts" / "probe.sh").is_file()
