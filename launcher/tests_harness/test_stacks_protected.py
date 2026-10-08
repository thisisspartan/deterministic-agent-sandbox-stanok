"""B1 (PLAN-AUDIT-2026-10-08): scripts/stacks/*.toml are contract files.

run.sh derives its STACKS registry (test_runner, test_glob, verdict_config)
from these manifests at every invocation, and scripts/ is a machine RW zone
whenever a ticket declares a path under it. A manifest left writable lets the
machine swap test_runner for `true` and get a PASS with no test ever run.

Red before the fix (the manifests are not in _protected_files), green after.
The conftest `repo` fixture already installs scripts/stacks/ into the hermetic
repo (CC-168), so these tests drive the real manifests. House style per
test_ro_protected_files.py: module-level import + monkeypatch.setattr on
stanok.REPO_ROOT (no importlib.reload — it would leak tampered globals into
other test modules that hold the same module object).
"""
import sys
from pathlib import Path

import pytest

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402

from conftest import repo, write  # noqa: E402,F401

STACKS = ("jq.toml", "js.toml", "py.toml")  # the shipped manifests (sorted)


# --- the protected list: one source ---------------------------------------------

def test_stack_manifests_are_protected(repo, monkeypatch):
    write(repo / "tests" / "a_test.py", "def test_a():\n    assert 1\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    protected = set(stanok._protected_files())
    for name in STACKS:
        assert f"scripts/stacks/{name}" in protected
    # The manifest and the :ro list are the same rule, not two policy lists.
    assert set(stanok._tests_manifest()) == protected


# --- the contract lock: the verdict bypass is caught ----------------------------

def test_manifest_edit_is_contract_violation(repo, monkeypatch):
    """The bypass: rewrite test_runner in a manifest during a turn."""
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    plan = stanok.SessionPlan(declared_paths=())
    before = stanok._tests_manifest()
    manifest = repo / "scripts" / "stacks" / "py.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n# tampered\n",
                        encoding="utf-8")
    job: dict = {}
    stanok._check_contract_lock(before, job, 1, plan)
    assert job.get("contract_lock_violations") == [
        "turn 1: MODIFIED: scripts/stacks/py.toml"]
    # The violation fails the run closed (rc=1, verifier FAIL) — not just logged.
    assert stanok._contract_lock_forced_fail(job, 1) == 1
    assert job["verifier"] == "FAIL"


def test_manifest_delete_is_contract_violation(repo, monkeypatch):
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    plan = stanok.SessionPlan(declared_paths=())
    before = stanok._tests_manifest()
    (repo / "scripts" / "stacks" / "jq.toml").unlink()
    job: dict = {}
    stanok._check_contract_lock(before, job, 1, plan)
    assert job.get("contract_lock_violations") == [
        "turn 1: DELETED: scripts/stacks/jq.toml"]


# --- anti-false-positive ---------------------------------------------------------

def test_new_manifest_declared_by_ticket_is_not_violation(repo, monkeypatch):
    """A ticket that declares a NEW stack manifest is allowed (new files are
    not in the before-snapshot; the declared path is exempt regardless)."""
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    plan = stanok.SessionPlan(declared_paths=("scripts/stacks/go.toml",))
    before = stanok._tests_manifest()
    write(repo / "scripts" / "stacks" / "go.toml", 'ext = "go"\n')
    job: dict = {}
    stanok._check_contract_lock(before, job, 1, plan)
    assert "contract_lock_violations" not in job


def test_unrelated_src_edit_is_not_violation(repo, monkeypatch):
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    write(repo / "src" / "mod.py", "x = 1\n")
    plan = stanok.SessionPlan(declared_paths=())
    before = stanok._tests_manifest()
    write(repo / "src" / "mod.py", "x = 2\n")
    job: dict = {}
    stanok._check_contract_lock(before, job, 1, plan)
    assert "contract_lock_violations" not in job
