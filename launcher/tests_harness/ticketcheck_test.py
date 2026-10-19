"""ticketcheck_test — unit tests for launcher/ticketcheck.py (CC-296).

tmp_path mini-trees only: the live tickets/ and evidence/ of the parent repo
do not reach the Pod, so every tree is built here — src/ tests/ docs/,
scripts/stacks/ with the REAL stack manifests copied from this repo
(read-only source), fake ticket files and fake accept files. The frozen
samples under launcher/tests_harness/fixtures_tickets/ are read-only references; the
subprocess boundary over them is launcher/tests_harness/ticketcheck_boundary_test.py
(host-authored). Here the API (load_registry / check_ticket / main) is
exercised in-process.
"""

import pathlib
import shutil

from launcher import ticketcheck

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_STACKS_SRC = _REPO_ROOT / "scripts" / "stacks"


# ---------------------------------------------------------------------------
# helpers (fixtures live in this file: conftest.py is not allowed)
# ---------------------------------------------------------------------------

def _tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """A mini repo: the writable zones + the real stack manifests (copied)."""
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
# load_registry — the test-name registry comes from scripts/stacks/*.toml
# ---------------------------------------------------------------------------

def test_load_registry_reads_test_glob_from_manifests(tmp_path):
    """The registry is the test_glob field of the manifests — the single
    source. Mutating a copied manifest proves no test-file names are
    hardcoded in the implementation."""
    tree = _tree(tmp_path)
    globs = ticketcheck.load_registry(str(tree))
    assert set(globs) == {"*_test.py", "*.test.js", "*.json"}

    py_toml = tree / "scripts" / "stacks" / "py.toml"
    py_toml.write_text(
        py_toml.read_text(encoding="utf-8").replace(
            'test_glob = "*_test.py"', 'test_glob = "*_spec.py"'),
        encoding="utf-8")
    globs = ticketcheck.load_registry(str(tree))
    assert "*_spec.py" in globs
    assert "*_test.py" not in globs


# ---------------------------------------------------------------------------
# clean tickets — positive cases (every stack glob claimed at least once)
# ---------------------------------------------------------------------------

def test_clean_ticket_yields_no_violations(tmp_path):
    tree = _tree(tmp_path)
    _write(tree, "tests/boundary_test.py", "# trusted pre-existing check\n")
    ticket = _write(tree, "tickets/TASK-DEMO-TT-1.md",
                    "impl: src/demo.py\n"
                    "test: tests/demo_test.py\n"
                    "docs: docs/demo.md\n"
                    "accept: tests/boundary_test.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert parse == []


def test_clean_ticket_multi_stack_test_names(tmp_path):
    """js/json test names are claimed by their stack globs too."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-2.md",
                    "impl: src/app.py\n"
                    "test: tests/app.test.js\n"
                    "test: tests/payload.json\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert parse == []


# ---------------------------------------------------------------------------
# UNCLAIMED-TEST-NAME — negative case; independence: location is fine here
# ---------------------------------------------------------------------------

def test_bad_test_name_rejected_exact_line(tmp_path):
    """Good location (tests/), bad name: ONLY the name rule fires."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-3.md",
                    "impl: src/preflight_demo.py\n"
                    "test: tests/test_preflight.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert parse == []
    assert violations == [
        "VIOLATION UNCLAIMED-TEST-NAME: tickets/TASK-DEMO-TT-3.md: test path "
        "'tests/test_preflight.py': basename 'test_preflight.py' matches no "
        "stack test_glob"]


# ---------------------------------------------------------------------------
# UNCLAIMED-TEST-PATH — negative case; independence: the name is fine here
# ---------------------------------------------------------------------------

def test_bad_test_location_rejected_exact_line(tmp_path):
    """Bad location (src/), good name: ONLY the location rule fires."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-4.md",
                    "impl: src/mod_demo.py\n"
                    "test: src/preflight_mod_test.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert parse == []
    assert violations == [
        "VIOLATION UNCLAIMED-TEST-PATH: tickets/TASK-DEMO-TT-4.md: test path "
        "'src/preflight_mod_test.py': must live under tests/"]


def test_bad_location_and_bad_name_report_both_location_first(tmp_path):
    """The rules are independent: a path violating both gets both lines,
    location before name."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-5.md",
                    "impl: src/helper.py\n"
                    "test: docs/checker.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert parse == []
    assert violations == [
        "VIOLATION UNCLAIMED-TEST-PATH: tickets/TASK-DEMO-TT-5.md: test path "
        "'docs/checker.py': must live under tests/",
        "VIOLATION UNCLAIMED-TEST-NAME: tickets/TASK-DEMO-TT-5.md: test path "
        "'docs/checker.py': basename 'checker.py' matches no stack test_glob"]


# ---------------------------------------------------------------------------
# accept: paths are checked like test: paths (kind shown in the line)
# ---------------------------------------------------------------------------

def test_accept_path_with_bad_name_is_rejected(tmp_path):
    tree = _tree(tmp_path)
    _write(tree, "tests/accept_check.py", "# trusted check, bad name\n")
    ticket = _write(tree, "tickets/TASK-DEMO-TT-6.md",
                    "impl: src/demo.py\n"
                    "test: tests/demo_test.py\n"
                    "accept: tests/accept_check.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert parse == []
    assert violations == [
        "VIOLATION UNCLAIMED-TEST-NAME: tickets/TASK-DEMO-TT-6.md: accept "
        "path 'tests/accept_check.py': basename 'accept_check.py' matches no "
        "stack test_glob"]


# ---------------------------------------------------------------------------
# only test:/accept: paths are checked — impl:/docs:/edit: are not
# ---------------------------------------------------------------------------

def test_non_test_kinds_are_not_checked(tmp_path):
    """impl:/docs:/edit: paths never trigger the rules, even with a
    test-like name outside tests/."""
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-7.md",
                    "impl: src/helper.py\n"
                    "impl: src/impl_bad.py\n"
                    "docs: docs/notes.md\n"
                    "edit: src/thing.py\n"
                    "test: tests/good_test.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert parse == []


# ---------------------------------------------------------------------------
# DUPLICATE-TICKET-NUMBER
# ---------------------------------------------------------------------------

def test_duplicate_ticket_number_pair_exact_lines(tmp_path):
    """Two files in one directory claiming (series, 10): each input file gets
    its own line naming the other. The -alt suffix variant collides with the
    bare number."""
    tree = _tree(tmp_path)
    a = _write(tree, "tickets/TASK-DEMO-TT-10.md",
               "impl: src/a.py\n"
               "test: tests/a_test.py\n"
               "run.sh: exists\n")
    b = _write(tree, "tickets/TASK-DEMO-TT-10-alt.md",
               "impl: src/b.py\n"
               "test: tests/b_test.py\n"
               "run.sh: exists\n")
    va, pa = _check(tree, a)
    vb, pb = _check(tree, b)
    assert pa == [] and pb == []
    assert va == [
        "VIOLATION DUPLICATE-TICKET-NUMBER: tickets/TASK-DEMO-TT-10.md: "
        "ticket number 10 also claimed by tickets/TASK-DEMO-TT-10-alt.md"]
    assert vb == [
        "VIOLATION DUPLICATE-TICKET-NUMBER: tickets/TASK-DEMO-TT-10-alt.md: "
        "ticket number 10 also claimed by tickets/TASK-DEMO-TT-10.md"]


def test_duplicate_number_zero_padded_collides(tmp_path):
    """The collision key is (series, int(num)) — 010 and 10 are the same."""
    tree = _tree(tmp_path)
    a = _write(tree, "tickets/TASK-DEMO-TT-10.md",
               "impl: src/a.py\n"
               "test: tests/a_test.py\n"
               "run.sh: exists\n")
    _write(tree, "tickets/TASK-DEMO-TT-010.md",
           "impl: src/z.py\n"
           "test: tests/z_test.py\n"
           "run.sh: exists\n")
    violations, parse = _check(tree, a)
    assert parse == []
    assert violations == [
        "VIOLATION DUPLICATE-TICKET-NUMBER: tickets/TASK-DEMO-TT-10.md: "
        "ticket number 10 also claimed by tickets/TASK-DEMO-TT-010.md"]


def test_no_duplicate_for_different_numbers_series_or_dirs(tmp_path):
    tree = _tree(tmp_path)
    a = _write(tree, "tickets/TASK-DEMO-TT-10.md",
               "impl: src/a.py\n"
               "test: tests/a_test.py\n"
               "run.sh: exists\n")
    _write(tree, "tickets/TASK-DEMO-TT-11.md",
           "impl: src/b.py\n"
           "test: tests/b_test.py\n"
           "run.sh: exists\n")
    _write(tree, "tickets/TASK-OTHER-TT-10.md",
           "impl: src/c.py\n"
           "test: tests/c_test.py\n"
           "run.sh: exists\n")
    _write(tree, "tickets/sub/TASK-DEMO-TT-10.md",
           "impl: src/d.py\n"
           "test: tests/d_test.py\n"
           "run.sh: exists\n")
    # non-ticket .md files in the same directory never collide:
    _write(tree, "tickets/README.md", "# notes\n")
    _write(tree, "tickets/notes.md", "# notes\n")
    violations, parse = _check(tree, a)
    assert violations == []
    assert parse == []


def test_path_rules_precede_the_duplicate_rule(tmp_path):
    """Within one file: declared-path rules (header order) first, then the
    duplicate line."""
    tree = _tree(tmp_path)
    _write(tree, "tickets/TASK-DEMO-TT-10-alt.md",
           "impl: src/b.py\n"
           "test: tests/b_test.py\n"
           "run.sh: exists\n")
    ticket = _write(tree, "tickets/TASK-DEMO-TT-10.md",
                    "impl: src/a.py\n"
                    "test: src/bad_loc_test.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert parse == []
    assert violations == [
        "VIOLATION UNCLAIMED-TEST-PATH: tickets/TASK-DEMO-TT-10.md: test path "
        "'src/bad_loc_test.py': must live under tests/",
        "VIOLATION DUPLICATE-TICKET-NUMBER: tickets/TASK-DEMO-TT-10.md: "
        "ticket number 10 also claimed by tickets/TASK-DEMO-TT-10-alt.md"]


def test_violation_order_follows_header_order(tmp_path):
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-8.md",
                    "impl: src/a.py\n"
                    "test: src/bad_loc_test.py\n"
                    "test: tests/bad_name.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert parse == []
    assert violations == [
        "VIOLATION UNCLAIMED-TEST-PATH: tickets/TASK-DEMO-TT-8.md: test path "
        "'src/bad_loc_test.py': must live under tests/",
        "VIOLATION UNCLAIMED-TEST-NAME: tickets/TASK-DEMO-TT-8.md: test path "
        "'tests/bad_name.py': basename 'bad_name.py' matches no stack "
        "test_glob"]


# ---------------------------------------------------------------------------
# PARSE — malformed header / unreadable file (rc 2, stderr)
# ---------------------------------------------------------------------------

def test_malformed_header_is_parse_error(tmp_path):
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-9.md",
                    "impl: src/malformed_demo.py\n"
                    "test: bad name.py\n"
                    "run.sh: exists\n")
    violations, parse = _check(tree, ticket)
    assert violations == []
    assert len(parse) == 1
    assert parse[0].startswith(
        "PARSE: tickets/TASK-DEMO-TT-9.md: invalid header:")


def test_malformed_header_main_rc2(tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-9.md",
                    "impl: src/malformed_demo.py\n"
                    "test: bad name.py\n"
                    "run.sh: exists\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 2
    assert out == ""
    assert err.startswith("PARSE: tickets/TASK-DEMO-TT-9.md: invalid header:")


def test_missing_file_is_parse_error(tmp_path):
    tree = _tree(tmp_path)
    violations, parse = _check(tree, "tickets/TASK-DEMO-TT-999.md")
    assert violations == []
    assert len(parse) == 1
    assert parse[0].startswith(
        "PARSE: tickets/TASK-DEMO-TT-999.md: unreadable:")


def test_missing_file_main_rc2(tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path)
    rc, out, err = _main(tree, monkeypatch, capsys, "tickets/TASK-DEMO-TT-999.md")
    assert rc == 2
    assert out == ""
    assert err.startswith("PARSE: tickets/TASK-DEMO-TT-999.md: unreadable:")


# ---------------------------------------------------------------------------
# main — exit codes 0/1/2 and the exact stdout/stderr streams
# ---------------------------------------------------------------------------

def test_main_clean_rc0_empty_output(tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path)
    _write(tree, "tests/boundary_test.py", "# trusted check\n")
    ticket = _write(tree, "tickets/TASK-DEMO-TT-1.md",
                    "impl: src/demo.py\n"
                    "test: tests/demo_test.py\n"
                    "docs: docs/demo.md\n"
                    "accept: tests/boundary_test.py\n"
                    "run.sh: exists\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 0
    assert out == ""
    assert err == ""


def test_main_violations_rc1_exact_stdout(tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path)
    ticket = _write(tree, "tickets/TASK-DEMO-TT-3.md",
                    "impl: src/preflight_demo.py\n"
                    "test: tests/test_preflight.py\n"
                    "run.sh: exists\n")
    rc, out, err = _main(tree, monkeypatch, capsys, ticket)
    assert rc == 1
    assert out == (
        "VIOLATION UNCLAIMED-TEST-NAME: tickets/TASK-DEMO-TT-3.md: test path "
        "'tests/test_preflight.py': basename 'test_preflight.py' matches no "
        "stack test_glob\n")
    assert err == ""


def test_main_parse_priority_over_violations_rc2(tmp_path, monkeypatch, capsys):
    """A PARSE-failed file skips its own rules; the other files are still
    processed; rc 2 wins over rc 1."""
    tree = _tree(tmp_path)
    bad_name = _write(tree, "tickets/TASK-DEMO-TT-3.md",
                      "impl: src/preflight_demo.py\n"
                      "test: tests/test_preflight.py\n"
                      "run.sh: exists\n")
    malformed = _write(tree, "tickets/TASK-DEMO-TT-9.md",
                       "impl: src/malformed_demo.py\n"
                       "test: bad name.py\n"
                       "run.sh: exists\n")
    rc, out, err = _main(tree, monkeypatch, capsys, bad_name, malformed)
    assert rc == 2
    assert out == (
        "VIOLATION UNCLAIMED-TEST-NAME: tickets/TASK-DEMO-TT-3.md: test path "
        "'tests/test_preflight.py': basename 'test_preflight.py' matches no "
        "stack test_glob\n")
    assert err.startswith("PARSE: tickets/TASK-DEMO-TT-9.md: invalid header:")


def test_main_files_processed_in_argv_order(tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path)
    loc = _write(tree, "tickets/TASK-DEMO-TT-4.md",
                 "impl: src/mod_demo.py\n"
                 "test: src/preflight_mod_test.py\n"
                 "run.sh: exists\n")
    name = _write(tree, "tickets/TASK-DEMO-TT-3.md",
                  "impl: src/preflight_demo.py\n"
                  "test: tests/test_preflight.py\n"
                  "run.sh: exists\n")
    rc, out, err = _main(tree, monkeypatch, capsys, loc, name)
    assert rc == 1
    assert out == (
        "VIOLATION UNCLAIMED-TEST-PATH: tickets/TASK-DEMO-TT-4.md: test path "
        "'src/preflight_mod_test.py': must live under tests/\n"
        "VIOLATION UNCLAIMED-TEST-NAME: tickets/TASK-DEMO-TT-3.md: test path "
        "'tests/test_preflight.py': basename 'test_preflight.py' matches no "
        "stack test_glob\n")
    assert err == ""
