"""Host-authored contract oracle for src/ticketcheck.py (PLAN-ORACLE-PRACTICE generalization, 2026-10-19; B1 tmp-isolation + B2 provenance tiers + B3 M4 fix applied 2026-10-19).

Execution isolation (B1): the oracle runs ONLY inside a session-scoped pytest
tmp_path mini-tree (fixture `tree`) copied from the tree this file lives in
(src, launcher, scripts/stacks, tests/fixtures — copies, never symlinks; plus
an empty docs/ dir, because the real tree ships one and parse_ticket_header
validates NEW top-level declared paths against existing directories). The
containing tree is read-only for this test: no tc-drill*, no
tests/dup_accept_check.py may ever be created outside pytest's tmp. src/
ticketcheck is executed as a real subprocess (`sys.executable -B -m
src.ticketcheck`, cwd = tree root) per the documented CLI contract (SPEC §2:
`python3 -m src.ticketcheck <ticket-file> ...` from the repo root); the
production module is never imported. The SPEC §2 unit-API line differs from
the implementation signature, so the oracle pins only the CLI boundary.

Provenance tiers (B2 — honest attribution; do NOT read this file as "all
literals host-authored"):
  CONTRACT (host-authored sources):
    C1, C2   tests/fixtures/tickets/README.md — signed exact strings 901/902
    C3       specs/SPEC-SELFHOST-TICKETCHECK.md §2 (first component != tests)
    C4       SPEC §2 (registry = test_glob matching, fnmatch) + the
             case-sensitivity is derived from `run.sh list` semantics
             (case-sensitive find -name), i.e. observable run.sh behavior
    C5       SPEC §2 (registry read from scripts/stacks/*.toml)
    C6       SPEC §2 (series + int(num), same directory)
    C7       SPEC §2 (rc 0/1/2, PARSE priority)
    C8a      README + signed fixture 904 (`invalid header:`)
    C10a     SPEC §2 (the checked rules apply to test:/accept: kinds)
  CHARACTERIZATION (implementation-pinned — the only sources are production
  code or machine-authored docs; NOT a host contract):
    C8b      `unreadable:` — docs/ticketcheck.md:76 (machine-authored,
             CC-296) + src/ticketcheck.py
    C9       input path echoed exactly as given, incl. a `..` component —
             src/ticketcheck.py docstring only
    C10b     duplicate identical accept lines deduplicate to one line —
             not documented anywhere

Claims (C1..C10) and their mutants (one-line changes in src/ticketcheck.py
only; each mutant reddens exactly its target test — see calibration below):
  C1 [contract]   exact signed UNCLAIMED-TEST-NAME line (fixture 901)  M1: msg wording (:185)
  C2 [contract]   exact signed UNCLAIMED-TEST-PATH line (fixture 902)  M2: msg wording (:180)
  C3 [contract]   tests/ (incl. nested) never location-flagged;         M3: `!= "tests"` ->
                  outside is                                            `!= "docs"` (:177)
  C4 [contract]   registry name semantics: good names clean, bad        M4: fnmatchcase(base, glob)
                  flagged, case-sensitive                                 -> fnmatchcase(base.lower(), glob) (:182)
  C5 [contract]   the js manifest's test_glob participates (a           M5: `.endswith(".toml")`
                  .test.js name is claimed)                             -> `.endswith("py.toml")` (:78)
  C6 [contract]   duplicate semantics: -suffix collides, zero-padding   M6: `int(m.group("num"))`
                  collides via int-normalization; cross-series and        -> `m.group("num")` (:127)
                  cross-directory same number are NOT collisions; each
                  input gets its own line naming the other file
  C7 [contract]   rc contract: clean -> 0 empty; violations -> 1;       M7: `if parse_failed:` ->
                  PARSE -> 2; PARSE priority over 1 (mixed run -> 2       `if parse_failed and not
                  AND both outputs present); zero input files -> 0         violations:` (:213)
  C8 PARSE line shape:                                                          M8a [contract] "invalid header:" ->
     `PARSE: <file-as-given>: invalid header: ...` /                              "bad header:" (:173)
     `... unreadable: ...`                                                      M8b [characterization]
                                                                                   "unreadable:" ->
                                                                                   "cannot read:" (:168)
  C9 [characterization] input paths echoed into messages exactly        M9: `for ticket_file in
                  as given                                              files:` -> normpath gen (:203)
  C10 accept: participates in the checked kinds AND duplicate            M10 [characterization,
      identical accept lines yield exactly one violation line             target of C10b dedup]:
                                                                          `if kind == "accept":` ->
                                                                          `if False and ...` (:110)
  (note: the earlier M4 formulation `fnmatchcase -> fnmatch` was a NO-OP on
  POSIX — os.path.normcase is identity; the actual mutant lowers the base.)

Calibration (RE-executed 2026-10-19 after the B1 fixture change; a test-body
edit invalidates the previous calibration; runner: `python -m pytest -q
-p no:cacheprovider -o pythonpath=src tests/ticketcheck_contract_test.py`
from each tree root; driver mutate.py):
  REFERENCE tree: 10 passed (rc=0); no files created outside pytest tmp.
  Every mutant = a copy of the ref tree with ONE line changed in
  src/ticketcheck.py only; every mutant reddened EXACTLY its target test,
  no collateral (full logs: logs/<mutant>.log):
  m1  RED test_c1_... (assert exact signed NAME line not in stdout)
  m2  RED test_c2_... (assert exact signed PATH line not in stdout)
  m3  RED test_c3_... (nested tests/ run no longer clean: location line != "")
  m4  RED test_c4_... (case-mismatched name no longer flagged: assert False)
  m5  RED test_c5_... (js glob dropped from registry: assert not True)
  m6  RED test_c6_... (zero-padding no longer collides: assert 0 == 1)
  m7  RED test_c7_... (mixed run returns 1 instead of 2: assert 1 == 2)
  m8a RED test_c8_... (PARSE prefix "invalid header:" missing: assert False)
  m8b RED test_c8_... (PARSE prefix "unreadable:" missing: assert False)
  m9  RED test_c9_... (input path normalized before echo: assert False)
  m10 RED test_c10_ (two accept lines -> two violations: assert 2 == 1)
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

LIVE_ROOT = pathlib.Path(__file__).resolve().parents[1]

_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "LANG": "C"}


@pytest.fixture(scope="session")
def tree(tmp_path_factory):
    """Session mini-tree: the ONLY tree this oracle may read or write.

    Copies (not symlinks — a symlink would let a write land in the live
    tree) of exactly what the CLI under test resolves from its cwd:
    src (the module under test), launcher (imported by ticketcheck for
    parse_ticket_header), scripts/stacks (the registry), tests/fixtures
    (the signed ticket samples). The containing tree is never written.
    An empty docs/ is created: parse_ticket_header requires a NEW top-level
    declared path to lie under an existing directory (a new top-level dir
    "has no safe rw carve-out") — the real stanok tree ships a docs/
    directory, so the mini-tree mirrors that topology.
    """
    root = tmp_path_factory.mktemp("tc-tree")
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(LIVE_ROOT / "src", root / "src", ignore=ignore)
    shutil.copytree(LIVE_ROOT / "launcher", root / "launcher", ignore=ignore)
    (root / "scripts").mkdir()
    shutil.copytree(LIVE_ROOT / "scripts" / "stacks", root / "scripts" / "stacks")
    (root / "tests").mkdir()
    shutil.copytree(LIVE_ROOT / "tests" / "fixtures", root / "tests" / "fixtures")
    (root / "docs").mkdir()
    return root


# signed literals, transcribed from tests/fixtures/tickets/README.md (host-authored)
NAME_901 = (
    "VIOLATION UNCLAIMED-TEST-NAME: tests/fixtures/tickets/TASK-STANOK-CC-901.md:"
    " test path 'tests/test_preflight.py': basename 'test_preflight.py'"
    " matches no stack test_glob"
)
PATH_902 = (
    "VIOLATION UNCLAIMED-TEST-PATH: tests/fixtures/tickets/TASK-STANOK-CC-902.md:"
    " test path 'src/preflight_mod_test.py': must live under tests/"
)
PARSE_904_PREFIX = (
    "PARSE: tests/fixtures/tickets/TASK-STANOK-CC-904.md: invalid header:"
)


def _run(tree, *args):
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "src.ticketcheck", *args],
        cwd=str(tree), capture_output=True, text=True, env=_ENV)
    return proc.returncode, proc.stdout, proc.stderr


def _ticket(tree, rel, lines):
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# C1 — the UNCLAIMED-TEST-NAME line is the exact signed string (fixture 901)
# ---------------------------------------------------------------------------

def test_c1_name_violation_line_is_the_exact_signed_string(tree):
    rc, out, err = _run(tree, "tests/fixtures/tickets/TASK-STANOK-CC-901.md")
    lines = out.splitlines()
    assert NAME_901 in lines          # exact signed line, not a substring check
    assert rc == 1
    assert err == ""


# ---------------------------------------------------------------------------
# C2 — the UNCLAIMED-TEST-PATH line is the exact signed string (fixture 902)
# ---------------------------------------------------------------------------

def test_c2_location_violation_line_is_the_exact_signed_string(tree):
    rc, out, err = _run(tree, "tests/fixtures/tickets/TASK-STANOK-CC-902.md")
    lines = out.splitlines()
    assert PATH_902 in lines
    assert rc == 1
    assert err == ""


# ---------------------------------------------------------------------------
# C3 — location semantics: a tests/ path, however nested, is never location-
# flagged; a first component other than tests/ IS flagged
# ---------------------------------------------------------------------------

def test_c3_tests_paths_including_nested_are_never_location_flagged(tree):
    _ticket(tree, "tc-drill/TASK-DRILL-962.md",
            ["test: tests/deep_ok/nested_ok_test.py", "run.sh: exists"])
    rc, out, err = _run(tree, "tc-drill/TASK-DRILL-962.md")
    assert out == "" and err == "" and rc == 0  # nested tests/ path: clean

    _ticket(tree, "tc-drill/TASK-DRILL-963.md",
            ["test: docs/docs_ok_test.py", "run.sh: exists"])
    rc, out, err = _run(tree, "tc-drill/TASK-DRILL-963.md")
    lines = out.splitlines()
    prefix = ("VIOLATION UNCLAIMED-TEST-PATH: tc-drill/TASK-DRILL-963.md:"
              " test path 'docs/docs_ok_test.py'")
    assert any(line.startswith(prefix) for line in lines)
    assert rc == 1


# ---------------------------------------------------------------------------
# C4 — name semantics from the registry: names matching a test_glob are clean,
# names matching none are flagged; matching is case-sensitive (fnmatchcase)
# ---------------------------------------------------------------------------

def test_c4_registry_name_semantics_good_clean_bad_flagged_case_sensitive(tree):
    # good py name under src/ (location-flagged, but the NAME must not be)
    _ticket(tree, "tc-drill/TASK-DRILL-966.md",
            ["test: src/ok_mod_test.py", "run.sh: exists"])
    rc, out, _ = _run(tree, "tc-drill/TASK-DRILL-966.md")
    assert not any(l.startswith("VIOLATION UNCLAIMED-TEST-NAME")
                   for l in out.splitlines())
    assert rc == 1

    # test-like name matching no test_glob -> flagged
    _ticket(tree, "tc-drill/TASK-DRILL-964.md",
            ["test: tests/BADNAME_test.PY", "run.sh: exists"])
    rc, out, _ = _run(tree, "tc-drill/TASK-DRILL-964.md")
    prefix = ("VIOLATION UNCLAIMED-TEST-NAME: tc-drill/TASK-DRILL-964.md:"
              " test path 'tests/BADNAME_test.PY'")
    assert any(l.startswith(prefix) for l in out.splitlines())
    assert rc == 1

    # plain non-matching name -> flagged
    _ticket(tree, "tc-drill/TASK-DRILL-967.md",
            ["test: tests/another_badname.py", "run.sh: exists"])
    rc, out, _ = _run(tree, "tc-drill/TASK-DRILL-967.md")
    assert any(l.startswith("VIOLATION UNCLAIMED-TEST-NAME: tc-drill/TASK-DRILL-967.md:"
                           " test path 'tests/another_badname.py'")
               for l in out.splitlines())
    assert rc == 1


# ---------------------------------------------------------------------------
# C5 — the registry is read from scripts/stacks/*.toml: the js manifest's
# test_glob participates, a name matching it is claimed (not flagged)
# ---------------------------------------------------------------------------

def test_c5_js_manifest_glob_claims_js_names(tree):
    _ticket(tree, "tc-drill/TASK-DRILL-965.md",
            ["test: src/js_drill.test.js", "run.sh: exists"])
    rc, out, _ = _run(tree, "tc-drill/TASK-DRILL-965.md")
    # name matches the js test_glob "*.test.js" -> must NOT be name-flagged
    assert not any(l.startswith("VIOLATION UNCLAIMED-TEST-NAME")
                   for l in out.splitlines())
    assert rc == 1  # the src/ location violation is still present


# ---------------------------------------------------------------------------
# C6 — duplicate semantics: (series, int(num)); -suffix collides, zero padding
# collides via int normalization; cross-series and cross-directory same number
# do NOT collide; each checked input gets its own line naming the other file
# ---------------------------------------------------------------------------

def test_c6_duplicate_ticket_number_semantics(tree):
    header_a = ["impl: src/drill_dup_a.py", "run.sh: exists"]
    header_b = ["impl: src/drill_dup_b.py", "run.sh: exists"]

    # -suffix collision: TASK-DRILL-955-dup.md has the same (series, 955)
    _ticket(tree, "tc-drill/TASK-DRILL-955.md", header_a)
    _ticket(tree, "tc-drill/TASK-DRILL-955-dup.md", header_b)
    rc, out, _ = _run(tree, "tc-drill/TASK-DRILL-955.md")
    dup_lines = [l for l in out.splitlines()
                 if l.startswith("VIOLATION DUPLICATE-TICKET-NUMBER:")]
    assert len(dup_lines) == 1
    assert "955" in dup_lines[0]
    assert "tc-drill/TASK-DRILL-955-dup.md" in dup_lines[0]
    assert rc == 1
    # ... and the other input gets its own line naming the first
    rc, out, _ = _run(tree, "tc-drill/TASK-DRILL-955-dup.md")
    dup_lines = [l for l in out.splitlines()
                 if l.startswith("VIOLATION DUPLICATE-TICKET-NUMBER:")]
    assert len(dup_lines) == 1
    assert "tc-drill/TASK-DRILL-955.md" in dup_lines[0]
    assert rc == 1

    # zero padding: (series, "0956") == (series, 956) after int normalization
    _ticket(tree, "tc-drill/TASK-DRILL-0956.md", header_a)
    _ticket(tree, "tc-drill/TASK-DRILL-956.md", header_b)
    rc, out, _ = _run(tree, "tc-drill/TASK-DRILL-0956.md")
    dup_lines = [l for l in out.splitlines()
                 if l.startswith("VIOLATION DUPLICATE-TICKET-NUMBER:")]
    assert len(dup_lines) == 1
    assert "956" in dup_lines[0]
    assert "tc-drill/TASK-DRILL-956.md" in dup_lines[0]
    assert rc == 1

    # cross-series, same number, same directory -> NOT a collision
    _ticket(tree, "tc-drill/TASK-DRILL-957.md", header_a)
    _ticket(tree, "tc-drill/TASK-OTHER-957.md", header_b)
    rc, out, err = _run(tree, "tc-drill/TASK-DRILL-957.md")
    assert out == "" and err == "" and rc == 0

    # same (series, num) in a DIFFERENT directory -> NOT a collision
    _ticket(tree, "tc-drill/TASK-DRILL-958.md", header_a)
    _ticket(tree, "tc-drill-b/TASK-DRILL-958.md", header_b)
    rc, out, err = _run(tree, "tc-drill/TASK-DRILL-958.md")
    assert out == "" and err == "" and rc == 0


# ---------------------------------------------------------------------------
# C7 — exit-code contract: 0 clean (incl. zero input files), 1 violations,
# 2 PARSE; PARSE priority over 1 (mixed run: rc 2 AND both outputs present)
# ---------------------------------------------------------------------------

def test_c7_exit_code_contract_and_parse_priority(tree):
    # zero input files: vacuously clean
    rc, out, err = _run(tree)
    assert rc == 0 and out == "" and err == ""

    # clean header (no test:/accept: declarations) -> 0, empty output
    _ticket(tree, "tc-drill/TASK-DRILL-961.md",
            ["impl: src/drill_clean.py", "run.sh: exists"])
    rc, out, err = _run(tree, "tc-drill/TASK-DRILL-961.md")
    assert rc == 0 and out == "" and err == ""

    # violations only -> 1, VIOLATION lines on stdout, nothing on stderr
    rc, out, err = _run(tree, "tests/fixtures/tickets/TASK-STANOK-CC-901.md")
    assert rc == 1 and out != "" and err == ""
    assert any(l.startswith("VIOLATION ") for l in out.splitlines())

    # PARSE only -> 2, PARSE on stderr, stdout empty
    rc, out, err = _run(tree, "tests/fixtures/tickets/TASK-STANOK-CC-904.md")
    assert rc == 2 and out == ""
    assert any(l.startswith("PARSE: ") for l in err.splitlines())

    # mixed: a PARSE-failed file AND a violation file -> rc 2 priority,
    # the non-parsed file's violation is still produced
    rc, out, err = _run(tree, "tests/fixtures/tickets/TASK-STANOK-CC-901.md",
                        "tests/fixtures/tickets/TASK-STANOK-CC-904.md")
    assert rc == 2
    assert any(l.startswith("VIOLATION ") for l in out.splitlines())
    assert any(l.startswith("PARSE: ") for l in err.splitlines())


# ---------------------------------------------------------------------------
# C8 — PARSE line shape: PARSE: <file-as-given>: invalid header: ... (bad
# header) and PARSE: <file-as-given>: unreadable: ... (missing file)
# ---------------------------------------------------------------------------

def test_c8_parse_line_shape_invalid_header_and_unreadable(tree):
    rc, out, err = _run(tree, "tests/fixtures/tickets/TASK-STANOK-CC-904.md")
    assert rc == 2 and out == ""
    assert any(l.startswith(PARSE_904_PREFIX) for l in err.splitlines())

    rc, out, err = _run(tree, "tc-drill/TASK-DRILL-997.md")  # never created
    assert rc == 2 and out == ""
    assert any(l.startswith("PARSE: tc-drill/TASK-DRILL-997.md: unreadable:")
               for l in err.splitlines())


# ---------------------------------------------------------------------------
# C9 — the input path is echoed into messages exactly as given (no
# normalization) — here with a path containing a ".." component
# ---------------------------------------------------------------------------

def test_c9_input_paths_are_echoed_exactly_as_given(tree):
    _ticket(tree, "tc-drill/TASK-DRILL-959.md",
            ["impl: src/echo_drill.py",
             "test: tests/echo_badname.py",
             "run.sh: exists"])
    given = "tc-drill/../tc-drill/TASK-DRILL-959.md"
    rc, out, _ = _run(tree, given)
    assert rc == 1
    assert any(l.startswith(f"VIOLATION UNCLAIMED-TEST-NAME: {given}:")
               for l in out.splitlines())


# ---------------------------------------------------------------------------
# C10 — accept: participates in the checked kinds, and duplicate identical
# accept lines are deduplicated into exactly one violation line
# ---------------------------------------------------------------------------

def test_c10_accept_declarations_are_checked_and_deduplicated(tree):
    # pre-existing under tests/ (the parser requires existence) with a name
    # matching no test_glob -> the accept kind must produce a violation
    (tree / "tests" / "dup_accept_check.py").write_text(
        "# host-authored drill helper: an existing tests/ file with a\n"
        "# name matching no stack test_glob\n", encoding="utf-8")
    _ticket(tree, "tc-drill/TASK-DRILL-960.md",
            ["impl: src/drill_accept.py",
             "accept: tests/dup_accept_check.py",
             "accept: tests/dup_accept_check.py",
             "run.sh: exists"])
    rc, out, _ = _run(tree, "tc-drill/TASK-DRILL-960.md")
    accept_name_lines = [l for l in out.splitlines()
                         if l.startswith("VIOLATION UNCLAIMED-TEST-NAME:"
                                        " tc-drill/TASK-DRILL-960.md:"
                                        " accept path 'tests/dup_accept_check.py'")]
    assert len(accept_name_lines) == 1  # participates, exactly once despite two lines
    assert rc == 1
