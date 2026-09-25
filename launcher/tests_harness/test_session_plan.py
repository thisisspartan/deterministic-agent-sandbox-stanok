"""T1 (CC-120): SessionPlan is the single source of file policy (I1).

Hermetic: parse a sample ticket header, build the plan exactly as
cmd_run does, and pin the T1 invariants:
  - declared_paths == mutable_paths (T1: no divergence)
  - git_mode == "ro"
  - the contract_lock exemption is generalized to mutable_paths:
    a mutable protected path is not flagged; a non-mutable one is.

CC-132 adds the single-source zone/kind pins:
  - sandbox.WRITABLE_ZONES is the only literal zone list; its consumers
    (hidden_files_gate, declared_carveout — CC-135 dropped prepare_workspace
    and _validate_declared_path from that list) read the constant
  - the ticket header kinds are exactly impl|test|docs|edit (`scripts` is
    a zone, not a kind)

CC-134 drops the former "evidence" carve-out from that list: evidence/ is no
longer mounted rw (the host publishes the verdict into it) — the boundary
itself is pinned in test_evidence_boundary.py.

CC-133 adds the create-vs-edit filesystem check:
  - assert_create_paths_are_new: a create-declared path that exists -> rc=13
    (the CC-119 fire16 retry1 case); `edit:` paths and genuinely new paths pass

CC-135 (T4) removes the `rw_zones` field: the container's rw carve-outs are
derived from the declared paths (declared_carveout / host_rw_paths) instead of
being a second policy list in the plan — pinned in test_t4_mounts.py.

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
    plan with mutable=declared (the plan carries no mount/protected lists —
    T4/CC-135 derives the rw mounts, T4b/CC-136 the :ro binds)."""
    declared, edit_paths, _ = stanok.parse_ticket_header(ticket_text)
    return stanok.SessionPlan(
        declared_paths=tuple(declared),
        mutable_paths=tuple(declared),
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
    assert plan.git_mode == "ro"
    # T5/CC-137: exactly four fields — the mount/protected lists are derived
    # (rw_zones gone with CC-135, protected_paths gone with the hook it fed,
    # bootstrap_paths gone with the bootstrap kind itself — CC-154).
    assert {f.name for f in dataclasses.fields(stanok.SessionPlan)} == {
        "declared_paths", "mutable_paths", "git_mode", "edit_paths"}


def test_plan_is_frozen():
    plan = _build_plan(_TICKET)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.declared_paths = ()


def test_contract_lock_set_is_the_manifest_not_a_plan_field():
    # T5/CC-137: "protected" is the manifest itself (one source, CC-136's
    # _protected_files); it is not copied into the plan. The set the post-turn
    # diff hashes is exactly the set host_ro_paths may bind :ro.
    plan = _build_plan(_TICKET)
    assert not hasattr(plan, "protected_paths")
    assert not hasattr(stanok, "_pretooluse_lock_hook")


def test_contract_lock_exempts_mutable_path(repo, monkeypatch):
    # Generalized run.sh exemption: a mutable protected path is not
    # flagged even when modified; a non-mutable protected path is.
    write(repo / "tests" / "x_test.py", "def test_x():\n    assert 1\n")
    (repo / "docs").mkdir()  # CC-135: a declared path needs an existing carve-out
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    before = stanok._tests_manifest()
    runsh = repo / "scripts" / "run.sh"
    orig = runsh.read_text(encoding="utf-8")
    try:
        runsh.write_text(orig + "# probe\n", encoding="utf-8")
        job = {}
        plan = _build_plan(_TICKET)
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


# --- CC-132: one source for zones/kinds ----------------------------------------

def test_zones_have_one_source():
    # The zone list is one literal in sandbox.py and one NAME (CC-132's
    # DEFAULT_RW_ZONES alias is gone — CC-134). It is the *declaration*
    # allow-list, not the mount set: T4/CC-135 derives the mounts per ticket
    # (declared_carveout), so the plan carries no zone field at all.
    assert not hasattr(stanok.sandbox, "DEFAULT_RW_ZONES")
    assert stanok.sandbox.WRITABLE_ZONES == ("src", "tests", "docs", "scripts")
    fields = {f.name for f in dataclasses.fields(stanok.SessionPlan)}
    assert "rw_zones" not in fields


def test_zone_consumers_read_the_constant(tmp_path, monkeypatch):
    # After CC-135 the constant has two readers: hidden_files_gate (which dirs
    # to scan) and declared_carveout (a bare zone name is undeclarable).
    # prepare_workspace no longer reads it — the zone dirs used to be the rw
    # mount points, and T4 derives the carve-outs from the ticket instead, so
    # nothing manufactures them any more.
    repo_dir = tmp_path / "repo"
    (repo_dir / "src").mkdir(parents=True)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo_dir))
    monkeypatch.setattr(stanok.sandbox, "WRITABLE_ZONES", ("src", "zoneA"))

    assert stanok.prepare_workspace(_build_plan("")) == 0
    assert not (repo_dir / "zoneA").exists()      # no manufactured zone dir
    assert stanok.declared_carveout("zoneA") is None       # a bare zone
    assert stanok.declared_carveout("zoneA/x.py") is None  # absent, no ancestor

    write(repo_dir / "zoneA" / ".secret", "")
    assert stanok.hidden_files_gate() is True     # zoneA is scanned now


def test_header_kinds_are_impl_test_docs_edit():
    declared, edit_paths, reset_none = stanok.parse_ticket_header(
        "impl: src/a.py\n"
        "test: tests/a_test.py\n"
        "docs: docs/a.md\n"
        "edit: tests/b_test.py\n"
    )
    assert declared == ["src/a.py", "tests/a_test.py", "docs/a.md",
                        "tests/b_test.py"]
    assert edit_paths == ["tests/b_test.py"]
    assert reset_none is False


def test_scripts_is_a_zone_not_a_kind():
    # `scripts:` is not a declaration line: it ends the header, so the impl:
    # line after it is never reached. The old docstring advertised it.
    declared, edit_paths, _ = stanok.parse_ticket_header(
        "scripts: x.sh\nimpl: src/a.py\n"
    )
    assert declared == []
    assert edit_paths == []


def test_bootstrap_is_not_a_kind():
    # CC-154 dropped `bootstrap:` with the root: a bootstrap ticket could only
    # be accepted in a repo where `scripts/run.sh` is absent, but verify_gate
    # gets the verdict FROM run.sh — so it was safe but unreachable. The line
    # is now not a declaration (it ends the header), so the ticket is rejected
    # as "no declaration" (rc=13) instead of silently carving out a top-level
    # file.
    declared, edit_paths, _ = stanok.parse_ticket_header(
        "bootstrap: pyproject.toml\n"
    )
    assert declared == []
    assert edit_paths == []
    assert not hasattr(stanok, "_validate_bootstrap_path")
    assert not hasattr(stanok, "precreate_bootstrap_paths")
    assert not hasattr(stanok, "_bootstrap_paths")


# --- CC-133: create-vs-edit derived from the filesystem -------------------------

def test_stale_create_path_is_a_defect(repo, monkeypatch):
    # The CC-119 fire16 retry1 header: `tests/fire_color16_test.py` already
    # existed but was declared as a create -> quarantine moved it aside, the
    # hook denied recreating it, the turn stalled. Now it is rc=13 up front.
    write(repo / "tests" / "fire_color16_test.py", "def test_x():\n    assert 1\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    declared, edit_paths, _ = stanok.parse_ticket_header(
        "test: tests/fire_fire16_test.py\n"
        "test: tests/fire_color16_test.py\n"
    )
    with pytest.raises(ValueError) as exc:
        stanok.assert_create_paths_are_new(declared, edit_paths)
    assert "tests/fire_color16_test.py" in str(exc.value)
    assert "edit: tests/fire_color16_test.py" in str(exc.value)


def test_create_paths_that_are_new_pass(repo, monkeypatch):
    write(repo / "tests" / "old_test.py", "def test_x():\n    assert 1\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    declared, edit_paths, _ = stanok.parse_ticket_header(
        "test: tests/new_test.py\n"
        "edit: tests/old_test.py\n"
        "impl: src/new.py\n"
    )
    stanok.assert_create_paths_are_new(declared, edit_paths)  # no raise


def test_edit_path_that_is_absent_is_not_a_defect(repo, monkeypatch):
    # Deliberately unchecked direction: `edit:` on a missing path is not
    # destructive (a first ticket in a new project may declare it before the
    # file exists).
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    stanok.assert_create_paths_are_new(["src/new.py"], ["scripts/run.sh"])
