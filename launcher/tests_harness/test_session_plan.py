"""T1 (CC-120): SessionPlan is the single source of file policy (I1).

Hermetic: parse a sample ticket header, build the plan exactly as
cmd_run does, and pin the T1 invariants:
  - declared_paths == mutable_paths (T1: no divergence)
  - rw_zones == the current hardcoded 5-tuple (sandbox.DEFAULT_RW_ZONES)
  - probe_specs == () and git_mode == "ro" (T2/T4 not yet wired)
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
    declared, _ = stanok.parse_ticket_header(ticket_text)
    return stanok.SessionPlan(
        declared_paths=tuple(declared),
        mutable_paths=tuple(declared),
        protected_paths=(),
        rw_zones=stanok.sandbox.DEFAULT_RW_ZONES,
        probe_specs=(),
        git_mode="ro",
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
    assert plan.probe_specs == ()
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
