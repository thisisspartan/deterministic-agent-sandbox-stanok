"""ticketcheck_edit_path_test — unit tests for the EDIT-PATH-MISSING class
of src/ticketcheck.py (CC-298).

tmp_path mini-trees only (the same convention as tests/ticketcheck_test.py):
the API (check_ticket / main) is exercised in-process over trees built here —
src/ tests/ docs/ plus the REAL stack manifests copied from this repo.
Fixtures live in this file (conftest.py is not allowed).

Contract under test (additive only — the three existing classes and their
order are pinned here too). The EDIT-PATH-MISSING rule is a CLI-layer rule
(observed through main: exact stdout lines + rc — the ticket's observable),
while check_ticket's unit contract is unchanged: a missing edit: path is NOT
a check_ticket violation (pinned by tests/ticketcheck_test.py):
  - a declared edit: path that is not an existing regular file -> exactly one
    line "VIOLATION EDIT-PATH-MISSING: <ticket-file>: edit path '<rel>'
    does not exist", after all existing violations of the file, in edit:
    declaration order;
  - scripts/run.sh is never flagged (absent or present);
  - duplicate identical edit: lines -> one line;
  - exit codes unchanged: violations -> 1, PARSE -> 2 (a PARSE-failed file
    skips ALL rules, including this one).
"""

import pathlib
import shutil

from src import ticketcheck

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_STACKS_SRC = _REPO_ROOT / "scripts" / "stacks"


# ---------------------------------------------------------------------------
# helpers (fixtures live in this file: conftest.py is not allowed)
# ---------------------------------------------------------------------------

def _tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """A mini repo: the writable zones + the real stack manifests (copied)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    for zone in ("src", "tests", "docs"):
        (tmp_path / zone).mkdir()
    stacks = tmp_path / "scripts" / "stacks"
    stacks.mkdir(parents=True)
    for manifest in sorted(_STACKS_SRC.glob("*.toml")):
        shutil.copy(manifest, stacks / manifest.name)
    return tmp_path


def _write(root: pathlib.Path, rel: str, text: str) -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel


def _check(tree: pathlib.Path, ticket_rel: str) -> tuple[list[str], list[str]]:
    registry = ticketcheck.load_registry(str(tree))
    return ticketcheck.check_ticket(ticket_rel, str(tree), registry)


def _main(tree: pathlib.Path, monkeypatch, capsys, *ticket_rels: str):
    monkeypatch.chdir(tree)
    rc = ticketcheck.main(list(ticket_rels))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


# ---------------------------------------------------------------------------
# EDIT-PATH-MISSING — the exact line and rc 1; negative: an existing file
# ---------------------------------------------------------------------------

def test_missing_edit_path_flagged_exact_line(tmp_path, monkeypatch, capsys):
    """A declared edit: path that does not exist -> exactly one line in the
    VIOLATION format on stdout, echoed with the ticket path as given; rc 1."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-EP-EP-1.md",
                    "edit: src/missing.py\n"
                    "Body: the file must be created by the ticket.\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 1
    assert out == (
        "VIOLATION EDIT-PATH-MISSING: tickets/TASK-EP-EP-1.md: edit path "
        "'src/missing.py' does not exist\n")
    assert err == ""


def test_existing_edit_path_not_flagged(tmp_path, monkeypatch, capsys):
    """The negative case: an edit: path that IS an existing regular file ->
    clean, rc 0, empty output."""
    tree = _tree(tmp_path)
    _write(tree, "src/thing.py", "# pre-existing\n")
    ticket = _write(tree, "tickets/TASK-EP-EP-2.md",
                    "edit: src/thing.py\n"
                    "Body.\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert parse == []
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 0
    assert out == ""
    assert err == ""


# ---------------------------------------------------------------------------
# the sole exception: scripts/run.sh is never flagged, absent or present
# ---------------------------------------------------------------------------

def test_scripts_run_sh_never_flagged(tmp_path, monkeypatch, capsys):
    """Bootstrap case: `edit: scripts/run.sh` with the file ABSENT is the
    parser's legalized bootstrap — never an EDIT-PATH-MISSING line. Present:
    also clean (it is an existing file anyway)."""
    absent = _tree(tmp_path / "absent")
    t1 = _write(absent, "tickets/TASK-EP-EP-3.md",
                "edit: scripts/run.sh\n"
                "Body: bootstrap the entrypoint.\n")
    violations, parse = _check(absent, t1)
    assert violations == []
    assert parse == []
    rc, out, err = _main(absent, monkeypatch, capsys, t1)
    assert rc == 0
    assert out == ""
    assert err == ""

    present = _tree(tmp_path / "present")
    _write(present, "scripts/run.sh", "#!/usr/bin/env bash\n")
    t2 = _write(present, "tickets/TASK-EP-EP-3.md",
                "edit: scripts/run.sh\n"
                "Body.\n")
    violations, parse = _check(present, t2)
    assert violations == []
    assert parse == []


# ---------------------------------------------------------------------------
# order: existing violations of the file first, EDIT-PATH-MISSING after them
# ---------------------------------------------------------------------------

def test_existing_violations_precede_edit_lines(tmp_path, monkeypatch,
                                                capsys):
    """A bad test: name AND a missing edit: path -> exactly two lines on
    stdout: the UNCLAIMED-TEST-NAME line first (existing rule), then
    EDIT-PATH-MISSING."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-EP-EP-4.md",
                    "test: tests/badname.py\n"
                    "edit: src/missing.py\n"
                    "Body.\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 1
    assert err == ""
    assert out == (
        "VIOLATION UNCLAIMED-TEST-NAME: tickets/TASK-EP-EP-4.md: test path "
        "'tests/badname.py': basename 'badname.py' matches no stack "
        "test_glob\n"
        "VIOLATION EDIT-PATH-MISSING: tickets/TASK-EP-EP-4.md: edit path "
        "'src/missing.py' does not exist\n")


def test_edit_lines_follow_the_duplicate_line(tmp_path, monkeypatch, capsys):
    """EDIT-PATH-MISSING comes AFTER all existing violations of the file,
    including the DUPLICATE-TICKET-NUMBER line."""
    tree = _tree(tmp_path)
    _write(tree, "tickets/TASK-EP-EP-9-alt.md",
           "impl: src/b.py\n"
           "test: tests/b_test.py\n"
           "Body.\n")
    ticket = _write(tree, "tickets/TASK-EP-EP-9.md",
                    "edit: src/missing.py\n"
                    "Body.\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 1
    assert err == ""
    assert out == (
        "VIOLATION DUPLICATE-TICKET-NUMBER: tickets/TASK-EP-EP-9.md: ticket "
        "number 9 also claimed by tickets/TASK-EP-EP-9-alt.md\n"
        "VIOLATION EDIT-PATH-MISSING: tickets/TASK-EP-EP-9.md: edit path "
        "'src/missing.py' does not exist\n")


# ---------------------------------------------------------------------------
# dedup: repeated identical edit: lines -> exactly one line
# ---------------------------------------------------------------------------

def test_duplicate_edit_declarations_flag_once(tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-EP-EP-5.md",
                    "edit: src/missing.py\n"
                    "edit: src/missing.py\n"
                    "Body.\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 1
    assert err == ""
    assert out == (
        "VIOLATION EDIT-PATH-MISSING: tickets/TASK-EP-EP-5.md: edit path "
        "'src/missing.py' does not exist\n")


# ---------------------------------------------------------------------------
# scope: only existence of edit: paths is checked — no name/location rules
# for edit:, no existence rules for impl:/test:/docs:
# ---------------------------------------------------------------------------

def test_missing_edit_under_tests_flagged_without_name_rule(tmp_path,
                                                            monkeypatch,
                                                            capsys):
    """edit: tests/missing.py under an existing tests/ -> flagged by the
    existence rule ONLY: the name/location rules never apply to edit:."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-EP-EP-6.md",
                    "edit: tests/missing.py\n"
                    "Body.\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 1
    assert err == ""
    assert out == (
        "VIOLATION EDIT-PATH-MISSING: tickets/TASK-EP-EP-6.md: edit path "
        "'tests/missing.py' does not exist\n")


def test_impl_and_test_paths_existence_not_checked(tmp_path):
    """Unchanged (N5): absent impl:/test:/docs: paths never trigger the new
    rule — existence of those paths is the launch gate's competence."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-EP-EP-12.md",
                    "impl: src/helper.py\n"
                    "test: tests/helper_test.py\n"
                    "docs: docs/notes.md\n"
                    "Body.\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert parse == []


# ---------------------------------------------------------------------------
# not a regular file: an existing directory is flagged; parser-jurisdiction
# cases stay PARSE (no EDIT line)
# ---------------------------------------------------------------------------

def test_edit_path_that_is_a_directory_flagged(tmp_path, monkeypatch, capsys):
    """`edit:` declares a FILE to modify in place: an existing directory is
    not a regular file -> flagged."""
    tree = _tree(tmp_path)
    (tree / "src" / "subdir").mkdir()
    ticket = _write(tree, "tickets/TASK-EP-EP-7.md",
                    "edit: src/subdir\n"
                    "Body.\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 1
    assert err == ""
    assert out == (
        "VIOLATION EDIT-PATH-MISSING: tickets/TASK-EP-EP-7.md: edit path "
        "'src/subdir' does not exist\n")


def test_bare_zone_edit_is_parse_error_not_violation(tmp_path):
    """`edit: src` (a bare zone name) is rejected by parse_ticket_header —
    a PARSE line, NOT an EDIT-PATH-MISSING line (parser jurisdiction)."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-EP-EP-13.md",
                    "edit: src\n"
                    "Body.\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert len(parse) == 1
    assert parse[0].startswith(
        "PARSE: tickets/TASK-EP-EP-13.md: invalid header:")


def test_edit_path_without_existing_ancestor_is_parse_error(tmp_path):
    """An undeclarable edit: path (no existing in-zone ancestor) is a PARSE
    error — the new rule never runs for a PARSE-failed file."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-EP-EP-14.md",
                    "edit: nodir/missing.py\n"
                    "Body.\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert len(parse) == 1
    assert parse[0].startswith(
        "PARSE: tickets/TASK-EP-EP-14.md: invalid header:")


# ---------------------------------------------------------------------------
# rc contract unchanged: PARSE wins over the new rule too
# ---------------------------------------------------------------------------

def test_malformed_header_with_missing_edit_is_parse_only_rc2(
        tmp_path, monkeypatch, capsys):
    """A malformed header + a missing edit: path -> PARSE on stderr only,
    rc 2, empty stdout: a PARSE-failed file skips ALL rules."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-EP-EP-11.md",
                    "edit: src/missing.py\n"
                    "test: bad name.py\n"
                    "Body.\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert len(parse) == 1
    assert parse[0].startswith(
        "PARSE: tickets/TASK-EP-EP-11.md: invalid header:")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 2
    assert out == ""
    assert err.startswith("PARSE: tickets/TASK-EP-EP-11.md: invalid header:")
