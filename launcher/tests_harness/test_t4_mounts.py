"""CC-135 (T4): the container's rw mounts are DERIVED from the ticket.

SPEC-SESSION-PLAN §File enforcement (T4) / audit §4 item 4: `SessionPlan`
carries no zone or mount list — `rw_zones` was write-only (nothing read it
after CC-134 deleted `DEFAULT_RW_ZONES`). One rule, `declared_carveout`,
turns a declared path into the rw carve-out it implies; the HOST applies the
same rule in main() before `docker run`, because the container builds its own
plan only after it is started.

The rule (fail-closed; one implementation behind the parse gate AND the
mounts, so the two cannot drift):
  - relative, no `..`, realpath inside the repo, not a bare zone name;
  - exists (file or dir) -> bind it itself: a per-FILE rw mount is possible
    when the source exists (T3, verified 2026-09-24: an existing file bound
    rw over the ro repo is writable, its siblings stay EROFS);
  - absent -> its NEAREST EXISTING ANCESTOR dir, which must be BELOW the repo
    root. Docker creates a missing bind SOURCE as a root-owned DIRECTORY, so
    an absent path cannot be file-bound at all; and binding the repo root
    itself rw would dissolve the boundary -> None (a new top-level path is
    refused with rc=13 at parse time).

The last test is the real `docker run` e2e the audit asked for: a declared
file is writable while a SIBLING in the same (repo :ro) directory is EROFS,
and an absent declared path is writable through its parent-dir carve-out.
"""
import dataclasses
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


def _carve(repo_dir, monkeypatch, rel):
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo_dir))
    return stanok.declared_carveout(rel)


# --- the derivation rule --------------------------------------------------------

def test_existing_file_carves_out_itself(repo, monkeypatch):
    write(repo / "src" / "mod.py", "x = 1\n")
    assert _carve(repo, monkeypatch, "src/mod.py") == "src/mod.py"


def test_existing_dir_carves_out_itself(repo, monkeypatch):
    (repo / "src" / "pkg").mkdir()
    assert _carve(repo, monkeypatch, "src/pkg") == "src/pkg"
    # A bare ZONE is the one existing dir that is not declarable (see below).
    assert _carve(repo, monkeypatch, "tests") is None


def test_absent_path_carves_out_nearest_existing_ancestor(repo, monkeypatch):
    assert _carve(repo, monkeypatch, "tests/new_test.py") == "tests"
    # Nested: src/pkg/ does not exist yet, so the carve-out is src — the
    # documented residual (Docker cannot bind a missing file source, and a
    # source under a missing dir would be created root-owned on the host).
    assert _carve(repo, monkeypatch, "src/pkg/mod.py") == "src"


def test_new_top_level_path_is_undeclarable(repo, monkeypatch):
    # dirname -> "" (the repo root itself, which must stay :ro) -> None.
    assert _carve(repo, monkeypatch, "newmod.py") is None
    assert _carve(repo, monkeypatch, "src2/mod.py") is None


def test_bare_zone_is_undeclarable(repo, monkeypatch):
    # Declaring the zone itself would make prepare_workspace quarantine the
    # whole tree, and the mount would be the zone wholesale — not a per-ticket
    # carve-out. A path INSIDE a zone is the declared unit.
    for rel in ("src", "tests", "tests/", "docs", "scripts"):
        assert _carve(repo, monkeypatch, rel) is None, rel


def test_traversal_and_symlink_escape_are_undeclarable(repo, monkeypatch, tmp_path):
    # NB: the `repo` fixture IS tmp_path — the "outside" dir must live beside
    # it, not inside it.
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (repo / "src" / "link").symlink_to(outside)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    for rel in ("/etc/passwd", "./src/mod.py", "../x", "src/../tests/x"):
        assert stanok.declared_carveout(rel) is None, rel
    # A symlink inside the repo resolving OUTSIDE: Docker resolves the bind
    # source's realpath, so this would smuggle the outside dir in (SEC-01).
    assert stanok.declared_carveout("src/link") is None
    assert stanok.declared_carveout("src/link/x.py") is None


# --- the derivation over a declared list ----------------------------------------

def test_host_rw_paths_dedupes_and_only_emits_existing_sources(repo, monkeypatch):
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    declared, edit_paths, _ = stanok.parse_ticket_header(
        "test: tests/a_test.py\n"
        "test: tests/b_test.py\n"
        "impl: src/c.py\n"
        "edit: tests/existing_test.py\n"
    )
    rw = stanok.host_rw_paths(declared)
    assert rw == ("tests", "src"), rw  # dedupe, ticket order
    for rel in rw:  # a carve-out source MUST exist: Docker would create it
        assert os.path.exists(repo / rel), rel


def test_every_declared_path_is_covered_by_a_carve_out(repo, monkeypatch):
    # The T4 contract, stated as a property: whatever the ticket declares, the
    # derived mount set makes that exact path writable (itself or its nearest
    # existing ancestor dir) — and nothing else in the repo is.
    write(repo / "docs" / "guide.md", "# g\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    declared = ["docs/guide.md", "tests/new_test.py", "src/mod.py"]
    rw = stanok.host_rw_paths(declared)
    for rel in declared:
        carve = stanok.declared_carveout(rel)
        assert carve in rw, (rel, rw)
        assert rel == carve or rel.startswith(carve + "/")
    assert "evidence" not in rw and ".git" not in rw


def test_header_rejects_undeclarable_path():
    # The gate and the mounts are the same rule: if no carve-out exists, the
    # header is refused (rc=13 upstream) instead of launching a container that
    # cannot write what the ticket asked for.
    with pytest.raises(ValueError) as exc:
        stanok.parse_ticket_header("impl: brand_new_top_level.py\n")
    assert "brand_new_top_level.py" in str(exc.value)


def test_plan_carries_no_mount_field():
    # I1: the mounts are derived, never a second policy list in the plan.
    fields = {f.name for f in dataclasses.fields(stanok.SessionPlan)}
    assert "rw_zones" not in fields


# --- real docker run: per-file rw over a ro directory ---------------------------

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_declared_file_rw_sibling_erofs(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    for rel in ("src", "tests", "docs"):
        (repo_dir / rel).mkdir(parents=True)
    (repo_dir / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    log = tmp_path / "logs"
    log.mkdir()
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo_dir))
    # `src/mod.py` exists -> file bind; `docs/new.md` is absent -> docs/ bind.
    rw = stanok.host_rw_paths(["src/mod.py", "docs/new.md"])
    assert rw == ("src/mod.py", "docs")

    cmd = (
        f"touch '{repo_dir}/src/mod.py' && echo FILE-RW-OK; "
        f"if touch '{repo_dir}/src/sibling.py' 2>/dev/null; "
        f"then echo SIBLING-OK; else echo SIBLING-DENIED; fi; "
        f"touch '{repo_dir}/docs/new.md' && echo PARENT-RW-OK; "
        f"if touch '{repo_dir}/tests/x.py' 2>/dev/null; "
        f"then echo UNDECLARED-OK; else echo UNDECLARED-DENIED; fi"
    )
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    name, argv = sandbox.sandbox_argv(str(repo_dir), str(log), image,
                                      ["bash", "-c", cmd], rw_paths=rw)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    finally:
        sandbox.docker_stop(name)
    assert "FILE-RW-OK" in proc.stdout, proc
    assert "SIBLING-DENIED" in proc.stdout, proc
    assert "PARENT-RW-OK" in proc.stdout, proc
    assert "UNDECLARED-DENIED" in proc.stdout, proc
