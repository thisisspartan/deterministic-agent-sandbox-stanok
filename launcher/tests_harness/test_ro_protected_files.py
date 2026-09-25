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
  - `edit:`-declared files stay writable (an explicit in-place contract),
  - a protected file outside every carve-out needs no bind (the repo `:ro`
    mount already covers it).

The last test is the real `docker run` e2e the audit asked of T5.
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

def test_protected_files_are_tests_and_runsh(repo, monkeypatch):
    write(repo / "tests" / "a_test.py", "def test_a():\n    assert 1\n")
    write(repo / "tests" / "sub" / "b_test.py", "def test_b():\n    assert 1\n")
    write(repo / "tests" / "__pycache__" / "a_test.cpython-313.pyc", "junk")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    protected = stanok._protected_files()
    assert set(protected) == {"tests/a_test.py", "tests/sub/b_test.py",
                              "scripts/run.sh"}
    # The manifest and the :ro list are the same rule, not two policy lists.
    assert set(stanok._tests_manifest()) == set(protected)


def test_protected_list_without_a_runsh(repo, monkeypatch):
    # Bootstrap: a missing scripts/run.sh is not protected (it may be created).
    write(repo / "tests" / "a_test.py", "def test_a():\n    assert 1\n")
    (repo / "scripts" / "run.sh").unlink()
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok._protected_files() == ["tests/a_test.py"]


# --- host_ro_paths --------------------------------------------------------------

def test_no_bind_when_nothing_is_under_a_carve_out(tmp_path, monkeypatch):
    _host_repo(tmp_path, monkeypatch)
    assert stanok.host_ro_paths(["src/new.py"], ("src",)) == ()


def test_protected_files_under_a_dir_carve_out_are_bound(tmp_path, monkeypatch):
    root = _host_repo(tmp_path, monkeypatch, tests=("old_test.py", "also_test.py"))
    declared, _, _ = stanok.parse_ticket_header("test: tests/new_test.py\n")
    rw = stanok.host_rw_paths(declared)
    assert rw == ("tests",)                      # absent path -> its parent dir
    ro = stanok.host_ro_paths(declared, rw)
    assert set(ro) == {"tests/old_test.py", "tests/also_test.py"}
    # Every protected file UNDER a carve-out is either declared or :ro-bound:
    # nothing under a rw mount stays writable by accident. (scripts/run.sh is
    # not under one here — the repo :ro mount already covers it.)
    for rel in stanok._protected_files():
        if any(rel == c or rel.startswith(c + "/") for c in rw):
            assert rel in ro or rel in declared, rel


def test_declared_edit_path_is_not_bound(tmp_path, monkeypatch):
    # `edit: tests/old_test.py` is an explicit in-place contract: it must stay
    # rw even though it is a protected file and tests/ is carved out.
    _host_repo(tmp_path, monkeypatch, tests=("old_test.py", "other_test.py"))
    declared, edits, _ = stanok.parse_ticket_header(
        "edit: tests/old_test.py\n"
        "test: tests/new_test.py\n"
    )
    assert edits == ["tests/old_test.py"]
    rw = stanok.host_rw_paths(declared)
    ro = stanok.host_ro_paths(declared, rw)
    assert "tests/old_test.py" not in ro
    assert ro == ("tests/other_test.py",)


def test_runsh_is_bound_only_when_scripts_is_carved_out(tmp_path, monkeypatch):
    _host_repo(tmp_path, monkeypatch)
    assert "scripts/run.sh" not in stanok.host_ro_paths([], ("tests",))
    # scripts/ becomes a carve-out only via an absent declared path under it.
    declared = ["scripts/new_helper.sh"]
    rw = stanok.host_rw_paths(declared)
    assert rw == ("scripts",)
    assert stanok.host_ro_paths(declared, rw) == ("scripts/run.sh",)


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
    ro = stanok.host_ro_paths(declared, rw)
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
