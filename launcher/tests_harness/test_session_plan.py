"""T1 (CC-120): SessionPlan is the single source of file policy (I1).

Hermetic: parse a sample ticket header, build the plan exactly as
cmd_run does, and pin the T1 invariants:
  - declared_paths == mutable_paths (T1: no divergence)
  - rw_zones == the current hardcoded 5-tuple (sandbox.DEFAULT_RW_ZONES)
  - git_mode == "ro" (T4 not yet wired)
  - protected_paths populated from the pre-session manifest snapshot
    (dataclasses.replace, exactly as run_continuous_session does)
  - the contract_lock exemption is generalized to mutable_paths:
    a mutable protected path is not flagged; a non-mutable one is.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_session_plan.py -q
"""
import dataclasses
import sys
from pathlib import Path

import pytest

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402

from conftest import repo, write


def _build_plan(ticket_text):
    """Mirror cmd_run's T1 construction: parse the header, then build the
    plan with mutable=declared, protected=(), rw_zones=DEFAULT_RW_ZONES."""
    declared, edit_paths, _ = stanok.parse_ticket_header(ticket_text)
    return stanok.SessionPlan(
        declared_paths=tuple(declared),
        mutable_paths=tuple(declared),
        protected_paths=(),
        rw_zones=stanok.sandbox.DEFAULT_RW_ZONES,
        git_mode="ro",
        edit_paths=tuple(edit_paths),
    )


_TICKET = (
    "# sample ticket\n"
    "\n"
    "impl: src/mod.py\n"
    "test: tests/mod_test.py\n"
    "docs: docs/mod.md\n"
)


def test_plan_fields_from_ticket_header():
    plan = _build_plan(_TICKET)
    assert plan.declared_paths == ("src/mod.py", "tests/mod_test.py", "docs/mod.md")
    assert plan.declared_paths == plan.mutable_paths
    assert plan.rw_zones == ("src", "tests", "docs", "scripts", "evidence")
    assert plan.git_mode == "ro"
    assert plan.protected_paths == ()


def test_plan_is_frozen():
    plan = _build_plan(_TICKET)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.declared_paths = ()


def test_protected_paths_from_hermetic_manifest(repo, monkeypatch):
    write(repo / "tests" / "x_test.py", "def test_x():\n    assert 1\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    manifest = stanok._tests_manifest()
    assert "tests/x_test.py" in manifest
    assert "scripts/run.sh" in manifest
    plan = dataclasses.replace(_build_plan(_TICKET),
                               protected_paths=tuple(manifest.keys()))
    assert plan.protected_paths == tuple(manifest.keys())
    assert "tests/x_test.py" in plan.protected_paths
    assert "scripts/run.sh" in plan.protected_paths


def test_contract_lock_exempts_mutable_path(repo, monkeypatch):
    # Generalized run.sh exemption: a mutable protected path is not
    # flagged even when modified; a non-mutable protected path is.
    write(repo / "tests" / "x_test.py", "def test_x():\n    assert 1\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    before = stanok._tests_manifest()
    runsh = repo / "scripts" / "run.sh"
    orig = runsh.read_text(encoding="utf-8")
    try:
        runsh.write_text(orig + "# probe\n", encoding="utf-8")
        job = {}
        plan = dataclasses.replace(_build_plan(_TICKET),
                                   protected_paths=tuple(before.keys()))
        stanok._check_contract_lock(before, job, 1, plan)
        assert any("scripts/run.sh" in v
                   for v in job.get("contract_lock_violations", [])), \
            f"non-mutable run.sh modification not flagged: {job}"
        job2 = {}
        plan2 = dataclasses.replace(plan, mutable_paths=("scripts/run.sh",))
        stanok._check_contract_lock(before, job2, 1, plan2)
        assert not job2.get("contract_lock_violations"), \
            f"mutable run.sh modification wrongly flagged: {job2}"
    finally:
        runsh.write_text(orig, encoding="utf-8")


_EDIT_TICKET = (
    "# sample ticket\n"
    "\n"
    "test: tests/new_test.py\n"
    "edit: tests/existing_test.py\n"
)


def test_edit_path_parsed_and_still_mutable():
    # CC-125: `edit:` is declared like any path (union) but also reported
    # separately so prepare_workspace can skip it.
    declared, edit_paths, reset_none = stanok.parse_ticket_header(_EDIT_TICKET)
    assert declared == ["tests/new_test.py", "tests/existing_test.py"]
    assert edit_paths == ["tests/existing_test.py"]
    assert reset_none is False
    plan = _build_plan(_EDIT_TICKET)
    assert plan.declared_paths == plan.mutable_paths
    assert plan.edit_paths == ("tests/existing_test.py",)


def test_prepare_workspace_quarantines_create_not_edit(repo, monkeypatch, tmp_path):
    write(repo / "tests" / "new_test.py", "stale create artifact\n")
    write(repo / "tests" / "existing_test.py", "modify me in place\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(stanok, "_live_dir", str(live))

    assert stanok.prepare_workspace(_build_plan(_EDIT_TICKET)) == 0

    # The create-declared path is moved aside (proves it is built from scratch).
    assert not (repo / "tests" / "new_test.py").exists()
    assert (live / "pre-existing" / "tests" / "new_test.py").exists()
    # The edit-declared path stays in the tree (no "recreate verbatim" dance).
    assert (repo / "tests" / "existing_test.py").exists()
    assert not (live / "pre-existing" / "tests" / "existing_test.py").exists()
