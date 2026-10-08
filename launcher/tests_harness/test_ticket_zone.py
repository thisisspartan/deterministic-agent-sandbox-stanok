"""Stage 1 (SPEC-VERDICT-INTEGRITY follow-up, operator decision 2026-10-09):
declared paths must lie in a writable zone — the cc217-impl incident.

The incident: ticket TASK-STANOK-CC-217 declared `edit: launcher` +
`impl: launcher/tests_harness/...`. declared_carveout accepted them (existing
path -> itself; absent path -> nearest existing ancestor `launcher/`), the
container started, and the machine spent ~141 s discovering that launcher/ is
physically unwritable: the repo is mounted :ro, write zones are
src/tests/docs/scripts only, settings.stanok.json denies Edit(launcher/**).

The rule: a path is declarable only when its FIRST component is one of
sandbox.WRITABLE_ZONES — for every kind (impl/test/docs/edit). Refusal is at
header parse (rc=13, before any docker run / workspace mutation). The zone
rule does NOT weaken CC-206: `edit:` on a pre-existing protected file stays
refused even though its zone is writable — the two checks are complementary.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_ticket_zone.py -q
"""
import pytest

from launcher import sandbox, ticket
from launcher.config import Config

from conftest import repo, write


def _cfg(r):
    return Config(repo_root=str(r))


# --- out-of-zone declarations are refused at parse (the cc217-impl shape) -----

def test_impl_under_existing_out_of_zone_dir_is_refused(repo):
    # The exact cc217-impl shape: an EXISTING out-of-zone directory made the
    # absent file declarable through the ancestor rule; the zone rule refuses.
    (repo / "launcher" / "tests_harness").mkdir(parents=True)
    with pytest.raises(ValueError) as exc:
        ticket.parse_ticket_header(_cfg(repo), "impl: launcher/x.py\n")
    assert "launcher/x.py" in str(exc.value)
    assert "writable zone" in str(exc.value).lower()


def test_test_kind_out_of_zone_is_refused(repo):
    (repo / "launcher" / "tests_harness").mkdir(parents=True)
    with pytest.raises(ValueError) as exc:
        ticket.parse_ticket_header(
            _cfg(repo), "test: launcher/tests_harness/x_test.py\n")
    assert "writable zone" in str(exc.value).lower()


def test_edit_existing_out_of_zone_dir_is_refused(repo):
    # `edit: launcher` — the declaration that started the incident: an existing
    # directory outside the zones (accepted by the old rule: itself as carve).
    (repo / "launcher").mkdir()
    with pytest.raises(ValueError) as exc:
        ticket.parse_ticket_header(_cfg(repo), "edit: launcher\n")
    assert "writable zone" in str(exc.value).lower()


def test_docs_kind_out_of_zone_is_refused(repo):
    (repo / "notes").mkdir()
    with pytest.raises(ValueError) as exc:
        ticket.parse_ticket_header(_cfg(repo), "docs: notes/guide.md\n")
    assert "writable zone" in str(exc.value).lower()


# --- in-zone declarations stay accepted -----------------------------------------

def test_edit_existing_src_file_accepted(repo):
    write(repo / "src" / "x.py", "x = 1\n")
    _, edit_paths, _ = ticket.parse_ticket_header(_cfg(repo), "edit: src/x.py\n")
    assert edit_paths == ["src/x.py"]


def test_impl_new_subdir_in_zone_accepted(repo):
    # New subdirectory under an existing zone dir: carve-out = src/ (unchanged).
    declared, _, _ = ticket.parse_ticket_header(_cfg(repo), "impl: src/new/mod.py\n")
    assert declared == ["src/new/mod.py"]
    assert ticket.declared_carveout(_cfg(repo), "src/new/mod.py") == "src"


def test_all_four_zones_declarable(repo):
    for zone in sandbox.WRITABLE_ZONES:
        (repo / zone).mkdir(exist_ok=True)
        ticket.parse_ticket_header(_cfg(repo), f"impl: {zone}/new/mod.py\n")


# --- unchanged refusals ----------------------------------------------------------

def test_bare_zone_name_still_refused(repo):
    for zone in sandbox.WRITABLE_ZONES:
        with pytest.raises(ValueError):
            ticket.parse_ticket_header(_cfg(repo), f"edit: {zone}\n")


def test_dotdot_and_absolute_still_refused(repo):
    for rel in ("../outside.py", "/etc/passwd", "src/../launcher/x.py", "./src/x.py"):
        with pytest.raises(ValueError):
            ticket.parse_ticket_header(_cfg(repo), f"impl: {rel}\n")


# --- the zone rule does not weaken CC-206 ---------------------------------------

def test_edit_on_existing_test_still_refused_by_cc206(repo):
    # tests/ IS a writable zone — the zone rule lets it through; the
    # protected-file gate must still refuse (complementary checks).
    write(repo / "tests" / "old_test.py", "def test_x():\n    assert 1\n")
    cfg = _cfg(repo)
    _, edit_paths, _ = ticket.parse_ticket_header(cfg, "edit: tests/old_test.py\n")
    with pytest.raises(ValueError) as exc:
        ticket.assert_edit_paths_are_not_protected(cfg, edit_paths)
    assert "tests/old_test.py" in str(exc.value)


def test_edit_on_existing_runsh_still_refused_by_cc206(repo):
    cfg = _cfg(repo)
    _, edit_paths, _ = ticket.parse_ticket_header(cfg, "edit: scripts/run.sh\n")
    with pytest.raises(ValueError):
        ticket.assert_edit_paths_are_not_protected(cfg, edit_paths)


def test_absent_runsh_bootstrap_still_legal(repo):
    (repo / "scripts" / "run.sh").unlink()
    cfg = _cfg(repo)
    _, edit_paths, _ = ticket.parse_ticket_header(cfg, "edit: scripts/run.sh\n")
    ticket.assert_edit_paths_are_not_protected(cfg, edit_paths)  # no raise


# --- refusal is at parse time: before any workspace mutation ---------------------

def test_refusal_before_any_workspace_mutation(repo):
    (repo / "launcher").mkdir()
    cfg = _cfg(repo)
    with pytest.raises(ValueError):
        ticket.parse_ticket_header(cfg, "edit: launcher\n")
    # parse_ticket_header is cmd_run's first ticket step (cli.py): a raise here
    # means prepare_workspace/docker never run — nothing was quarantined.
    assert (repo / "launcher").is_dir()
