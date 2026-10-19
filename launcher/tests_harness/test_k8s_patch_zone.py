"""Wave C (operator spec 2026-10-19, TASK-NEXT-AFTER-REBOOT-2026-10-20 §7) —
patch_gate as an ALLOW-LIST zone gate.

The zone question ("may this patch touch this path at all?") is decided by
`zones.WRITABLE_ZONES` (the existing single literal): the FIRST component of
every path the patch touches — every parsed path, and BOTH endpoints of a
rename/copy — must be a writable zone; everything else (launch.sh,
launcher/**, .claude/**, Dockerfile, k8s/**, root files) is REJECTED before
apply, on the existing host-issued CONTRACT-FAIL channel. Symlinks/gitlinks
stay REJECT-always. The two checks stay separate: this gate answers "zone?",
the manifest comparison answers "declared/protected?".

The path source is the machine parser `git apply --numstat -z` run in an
empty temp dir (pure parser, no tree required): numstat yields the RAW
paths — names with spaces and non-ASCII survive verbatim, which the regex
headers could not represent (space: no match at all; non-ASCII: quoted
octal garbage). A git parse failure or a header<->parsed-path count mismatch
is a PATCH-PARSE violation (fail closed).

Provenance of expected values:
  - patch bytes: produced HERE by real git commits + `git diff HEAD~1 HEAD`
    (the Pod-side equivalent: the Pod re-inits its own git and its patch is
    `git diff base..HEAD`), forced `-c core.quotepath=true`;
  - the quoted octal rendering of non-ASCII paths and the UNQUOTED rendering
    of space-containing paths: observed git behavior (host probes
    /tmp/wc-probe.py + /tmp/wc-probe2.py, 2026-10-19/20) — asserted here as
    fixture mechanism facts, and the fixture NAMES are host-authored;
  - the `deleted file mode 120000` rendering of a deleted symlink, and the
    C-style quoting of non-ASCII `rename from` endpoints: observed git
    behavior (the header-rendering probes cover both shapes), asserted here
    as fixture mechanism facts;
  - the `index … 120000` relink rendering (no mode line), the NAMED-escape
    rendering (`\\a \\b \\f \\r \\v`, never octal) of control characters in
    quoted paths, and Python `str.splitlines()` splitting content on
    \\x0c/U+2028 while git splits only on \\n: observed behavior (host
    probes /tmp/wave-c-logs/probe-r2.py + probe-r2b, 2026-10-19),
    asserted here as fixture mechanism facts;
  - violation words (ZONE/SYMLINK/PATCH-PARSE): the gate's contract form per
    the operator spec 2026-10-19 (allow-list; machine-sourced paths;
    fail-closed parse).
Tests:
  1  a patch modifying launch.sh            -> ZONE rejection
  2  a patch modifying launcher/gates.py    -> ZONE rejection
  3  a patch creating root/TCB files        -> every path ZONE-rejected
     (.claude/settings.json, Dockerfile, k8s/x.yaml, README.md,
      pyproject.toml, ARCHITECTURE.md)
  4  symlink `docs/with space`              -> SYMLINK rejection naming the
     exact path (git renders space paths unquoted — the old regex lost them)
  5  symlink `docs/nonäscii`                -> SYMLINK rejection naming the
     decoded exact path (git renders it octal-quoted — asserted in bytes)
  5b symlink deletion (`deleted file mode   -> SYMLINK rejection; REJECT-
     120000)                                  always covers every rendering
                                              (B1a-review finding 1, operator
                                              2026-10-20; RED-first: the
                                              pre-hardening gate returned [])
 6  rename src/a.py -> launcher/b.py       -> ZONE (destination)
  7  rename launcher/a.py -> src/b.py       -> ZONE (SOURCE endpoint — it is
     only visible in the rename header, numstat reports destinations only)
  8  new files under src/, tests/, docs/, scripts/ -> pass (regression:
     legitimate machine patches keep working; protected-file manifest is a
     separate gate)
  9  a `diff --git` header git cannot parse -> PATCH-PARSE
 10  git-rejected malformed patch (truncated hunk, invalid mode) ->
     PATCH-PARSE
11  rename `launcher/nonäscii.py` ->      -> ZONE on the octal-DECODED
    src/b.py (quoted `rename from`)          source endpoint — the machine
                                             reports only src/b.py, the
                                             quoted source is header-only
12  a symlink whose only diff rendering is  -> covered by 5b: every 120000
    `deleted file mode 120000`                 form is REJECT-always
13  git subprocess TIMEOUT                    -> PATCH-PARSE. A real timeout
    cannot be forced deterministically, so the branch is exercised via a
    monkeypatched subprocess.run (stated honestly: this is the gate's own
    fail-closed branch, not git behavior)
14  zone-lookalike paths: `srcx/a.py`,       -> ZONE rejection of each:
    `docs_evil/x.py`, root file `tests`         MEMBERSHIP of the first
                                                component, not prefix; a
                                                single-segment path is a root
                                                FILE named like a zone, not
                                                inside tests/ (operator gap
                                                list 2026-10-20; fixture
                                                names host-authored)
15  a genuine new-file patch whose content   -> PASS ([]). The gate splits
    line carries U+000C or U+2028               the text ONLY on \\n, like
                                                git; str.splitlines() also
                                                splits on those bytes and
                                                fabricated a phantom header
                                                (RED-first: the gate said
                                                "2 file headers vs 1 parsed
                                                paths")
16  relink an existing symlink               -> SYMLINK rejection. git
                                              renders a content relink ONLY
                                              as `index … 120000`, no mode
                                              line (measured); RED-first:
                                              the gate returned []
17a rename with a control character in the   -> ZONE rejection naming the
    SOURCE endpoint name                        EXACT decoded name; git
                                              quotes it with the NAMED
                                              escape \\f, the old decoder
                                              emitted the bare letter and
                                              named a wrong path
17b unit: _git_unquote named-escape set      -> byte-exact decode of
                                              \\a \\b \\t \\n \\v \\f \\r
                                              \\" \\\\ (measured rendering)
18a/b/c parser-ENVIRONMENT failure             -> PATCH-PARSE, never an
    (variant 2, prepared for operator          exception out of the gate;
    decision 2026-10-19, NOT part of the       18c also proves the temp dir
    core candidate)                            created before the failure is
                                               removed

Run: <stanok venv>/bin/python -m pytest launcher/tests_harness/test_k8s_patch_zone.py -q
"""
import os
import subprocess

import pytest

from launcher import k8s

GIT = ["git", "-c", "user.email=wc@wave.c", "-c", "user.name=wc",
       "-c", "commit.gpgsign=false", "-c", "core.quotepath=true"]


def _git(*args, cwd):
    r = subprocess.run(GIT + list(args), cwd=str(cwd), capture_output=True,
                       text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr}"


def _commit(repo, files):
    for p, body in files.items():
        full = repo / p
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "base", cwd=repo)


def _change_patch(repo, mutate):
    """Commit the mutation the way the Pod does it, then produce the exact
    `git diff HEAD~1 HEAD` bytes that become changes.patch."""
    mutate(repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "change", cwd=repo)
    out = subprocess.run(GIT + ["diff", "HEAD~1", "HEAD"], cwd=str(repo),
                         capture_output=True)
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    return out.stdout


def _base(tmp_path, files):
    _git("init", "-q", cwd=tmp_path)
    _commit(tmp_path, files)
    return tmp_path


def _gate(patch_bytes):
    # the production entry: strict decode of the exact bytes, then the gate
    return k8s.patch_gate(k8s.strict_patch_text(patch_bytes))


# --- 1/2: TCB files the deny-list never checked ---------------------------

def test_launch_sh_modification_zone_rejected(tmp_path):
    repo = _base(tmp_path, {"launch.sh": "#!/bin/sh\necho old\n",
                            "src/m.py": "x\n"})
    patch = _change_patch(repo, lambda r: (r / "launch.sh").write_text(
        "#!/bin/sh\necho new\n"))
    v = _gate(patch)
    assert any("ZONE" in x and "launch.sh" in x for x in v), v


def test_launcher_gates_modification_zone_rejected(tmp_path):
    repo = _base(tmp_path, {"launcher/gates.py": "old\n", "src/m.py": "x\n"})
    patch = _change_patch(repo, lambda r: (r / "launcher/gates.py").write_text(
        "new\n"))
    v = _gate(patch)
    assert any("ZONE" in x and "launcher/gates.py" in x for x in v), v


# --- 3: root/TCB files, one multi-file commit -----------------------------

ROOT_NEW = {
    "README.md": "r\n",
    "pyproject.toml": "[tool]\n",
    "Dockerfile": "FROM x\n",
    "k8s/x.yaml": "a: 1\n",
    ".claude/settings.json": "{}\n",
    "ARCHITECTURE.md": "a\n",
}


def test_root_tcb_files_zone_rejected(tmp_path):
    repo = _base(tmp_path, {"src/keep.py": "x\n"})
    patch = _change_patch(repo, lambda r: [
        ((r / p).parent.mkdir(parents=True, exist_ok=True),
         (r / p).write_text(b)) for p, b in ROOT_NEW.items()])
    v = _gate(patch)
    for p in ROOT_NEW:
        assert any("ZONE" in x and p in x for x in v), (p, v)


# --- 4/5: the verbatim PoC paths — quoted/space names survive -------------

def test_symlink_with_space_rejected_exact_name(tmp_path):
    repo = _base(tmp_path, {"docs/plain.txt": "x\n"})

    def mutate(r):
        os.symlink("plain.txt", str(r / "docs" / "with space"))

    patch = _change_patch(repo, mutate)
    # mechanism fact (probed): git renders space paths UNQUOTED in headers —
    # this is the exact byte shape that made the old regexes lose the file.
    assert b"diff --git a/docs/with space b/docs/with space" in patch
    v = _gate(patch)
    assert any("SYMLINK" in x and "docs/with space" in x for x in v), v


def test_symlink_nonascii_rejected_exact_name(tmp_path):
    repo = _base(tmp_path, {"docs/plain.txt": "x\n"})

    def mutate(r):
        os.symlink("plain.txt", str(r / "docs" / "nonäscii"))

    patch = _change_patch(repo, mutate)
    # mechanism fact (probed): core.quotepath renders non-ASCII octal-quoted
    # in headers; the old gate only ever saw the quoted garbage.
    assert rb"docs/non\303\244scii" in patch
    v = _gate(patch)
    assert any("SYMLINK" in x and "docs/nonäscii" in x for x in v), v


# --- 4b: symlink deletion (B1a-review finding 1, operator 2026-10-20) ------

def test_symlink_deletion_rejected(tmp_path):
    # `deleted file mode 120000` — a symlink removed by the patch is still a
    # symlink in the diff's filemode vocabulary: REJECT-always covers every
    # rendering. RED-first: the pre-hardening _MODE_SYMLINK_RE matched only
    # old/new/new-file forms and the patch passed with [].
    _git("init", "-q", cwd=tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "target.txt").write_text("x\n")
    os.symlink("target.txt", str(tmp_path / "docs" / "link"))
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-qm", "base", cwd=tmp_path)
    patch = _change_patch(tmp_path, lambda r: (r / "docs" / "link").unlink())
    # mechanism fact (probed rendering behavior): a deleted symlink is
    # rendered `deleted file mode 120000` — asserted so the fixture cannot
    # drift silently.
    assert b"deleted file mode 120000" in patch
    v = _gate(patch)
    assert any("SYMLINK" in x and "docs/link" in x for x in v), v


# --- 6/7: rename endpoints -------------------------------------------------

def test_rename_into_tcb_zone_rejected(tmp_path):
    repo = _base(tmp_path, {"src/a.py": "x\n", "docs/keep.txt": "k\n"})

    def mutate(r):
        (r / "launcher").mkdir()
        _git("mv", "src/a.py", "launcher/b.py", cwd=r)

    patch = _change_patch(repo, mutate)
    v = _gate(patch)
    assert any("ZONE" in x and "launcher/b.py" in x for x in v), v


def test_rename_from_tcb_source_endpoint_zone_rejected(tmp_path):
    repo = _base(tmp_path, {"launcher/a.py": "x\n", "src/keep.py": "k\n"})

    def mutate(r):
        _git("mv", "launcher/a.py", "src/b.py", cwd=r)

    patch = _change_patch(repo, mutate)
    v = _gate(patch)
    # numstat reports only the destination (src/b.py, zone-legal); the
    # SOURCE endpoint launcher/a.py is visible only in the rename header.
    assert any("ZONE" in x and "launcher/a.py" in x for x in v), v


def test_rename_quoted_source_endpoint_zone_rejected(tmp_path):
    # _git_unquote claim: numstat reports only src/b.py (zone-legal); the
    # SOURCE endpoint arrives octal-quoted in `rename from` and must be
    # judged decoded — the unquoted test 7 does not exercise the decoder.
    repo = _base(tmp_path, {"launcher/nonäscii.py": "x\n",
                            "src/keep.py": "k\n"})

    def mutate(r):
        _git("mv", "launcher/nonäscii.py", "src/b.py", cwd=r)

    patch = _change_patch(repo, mutate)
    # mechanism fact (probed): core.quotepath quotes non-ASCII rename
    # endpoints; the raw bytes carry the octal escape, not the name.
    assert rb'rename from "launcher/non\303\244scii.py"' in patch
    v = _gate(patch)
    assert any("ZONE" in x and "launcher/nonäscii.py" in x for x in v), v


# --- 8: regression — legitimate machine patches still pass -----------------

def test_writable_zone_paths_pass(tmp_path):
    repo = _base(tmp_path, {"src/keep.py": "x\n"})

    def mutate(r):
        for p, body in {"src/new.py": "n\n", "tests/new_test.py": "n\n",
                        "docs/new.md": "n\n", "scripts/new.sh": "n\n"}.items():
            (r / p).parent.mkdir(parents=True, exist_ok=True)
            (r / p).write_text(body)

    assert _gate(_change_patch(repo, mutate)) == []


# --- 9/10: fail-closed parse -----------------------------------------------

def test_unparseable_header_is_parse_violation(tmp_path):
    # shape confirmed by host probe: git apply --numstat parses zero paths
    # here (rc=0) while the text carries a `diff --git` header — the
    # header<->path count check must flag it.
    patch = b"diff --git a/src/x.py b/src/x.py\nrandom junk here\n"
    v = _gate(patch)
    assert any("PATCH-PARSE" in x for x in v), v


def test_truncated_hunk_is_parse_violation(tmp_path):
    # shape confirmed by host probe: git apply --numstat rc=128
    # ("corrupt patch") — the gate must fail closed, never return [].
    patch = (b"diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n"
             b"+++ b/src/x.py\n@@ -1,5 +1,5 @@\n-only one line\n")
    v = _gate(patch)
    assert any("PATCH-PARSE" in x for x in v), v


def test_timeout_is_parse_violation(monkeypatch):
    # honest statement: a REAL timeout cannot be forced deterministically;
    # this exercises the gate's OWN fail-closed branch (subprocess.run
    # raising TimeoutExpired -> paths=None -> PATCH-PARSE), not git behavior.
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)

    monkeypatch.setattr(k8s.subprocess, "run", fake_run)
    patch = (b"diff --git a/src/x.py b/src/x.py\n--- /dev/null\n"
             b"+++ b/src/x.py\n@@ -0,0 +1 @@\n+x\n")
    v = _gate(patch)
    assert any("PATCH-PARSE" in x for x in v), v


# --- 14: zone-lookalike boundary (operator gap list 2026-10-20) -----------

def test_zone_lookalike_paths_and_root_zone_name_rejected(tmp_path):
    # allow-list = MEMBERSHIP of the first component under a zone directory,
    # never a string prefix; a single-segment path is a root FILE named like
    # a zone, not a file inside that zone. Fixture names host-authored.
    repo = _base(tmp_path, {"src/keep.py": "x\n"})

    def mutate(r):
        for p, body in {"srcx/a.py": "n\n", "docs_evil/x.py": "n\n",
                        "tests": "n\n"}.items():
            full = r / p
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(body)

    patch = _change_patch(repo, mutate)
    v = _gate(patch)
    for p in ("tests", "srcx/a.py", "docs_evil/x.py"):
        assert any("ZONE" in x and x.endswith(p) for x in v), (p, v)


# --- 15: line splitting — git splits ONLY on \n (operator item 2026-10-20) --
# RED-first fixtures carry the exact defect bytes: measured in probe-r2.py
# (2026-10-19) that str.splitlines() splits a string on \x0c and U+2028,
# and the then-current gate answered "PATCH-PARSE: 2 file headers vs 1
# parsed paths" on these exact bytes — a genuine patch falsely rejected.

_FORMFEED = b"\x0c"           # U+000C form feed
_LINE_SEP = b"\xe2\x80\xa8"   # U+2028 LINE SEPARATOR, UTF-8 bytes


def _new_file_patch(sep: bytes) -> bytes:
    """A genuine single-file new-file patch whose ONLY content line embeds
    a non-\\n line separator: `diff --git` appears mid-line as literal
    content, not as a header."""
    return (b"diff --git a/src/fake.py b/src/fake.py\nnew file mode 100644\n"
            b"index 0000000..1111111\n--- /dev/null\n+++ b/src/fake.py\n"
            b"@@ -0,0 +1 @@\n+foo" + sep + b"diff --git a/decoy b/decoy\n")


def test_formfeed_content_line_passes_gate():
    patch = _new_file_patch(_FORMFEED)
    # mechanism anchors (measured): the separator sits INSIDE the added
    # line, and the MACHINE parser sees exactly one path — the header must
    # not be real.
    assert b"+foo" + _FORMFEED in patch
    assert k8s._numstat_paths(k8s.strict_patch_text(patch)) == ["src/fake.py"]
    assert _gate(patch) == []


def test_line_separator_content_line_passes_gate():
    patch = _new_file_patch(_LINE_SEP)
    assert b"+foo" + _LINE_SEP in patch
    assert k8s._numstat_paths(k8s.strict_patch_text(patch)) == ["src/fake.py"]
    assert _gate(patch) == []


# --- 16: symlink CONTENT relink — `index … 120000`, no mode line -----------

def test_symlink_relink_index_form_rejected(tmp_path):
    # Measured rendering (probe-r2.py): relinking an existing symlink is
    # rendered with NO mode line at all — the 120000 mode appears only in
    # the `index <old>..<new> 120000` line. RED-first: the then-current
    # gate returned [] (the 160000 index form was covered, the 120000 one
    # was not).
    _git("init", "-q", cwd=tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "target.txt").write_text("x\n")
    os.symlink("target.txt", str(tmp_path / "docs" / "link"))
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-qm", "base", cwd=tmp_path)

    def mutate(r):
        (r / "docs" / "link").unlink()
        os.symlink("target2.txt", str(r / "docs" / "link"))

    patch = _change_patch(tmp_path, mutate)
    assert any(ln.startswith(b"index ") and ln.endswith(b"120000")
               for ln in patch.split(b"\n")), patch
    assert b"mode" not in patch  # the whole defect: no mode line rendered
    v = _gate(patch)
    assert any("SYMLINK" in x and "docs/link" in x for x in v), v


# --- 17: control characters in rename endpoints (operator item 2026-10-20) --

def test_control_char_rename_source_endpoint_exact_name(tmp_path):
    # Measured (probe-r2b.py): git quotes a control character in a path
    # with the NAMED escape (\f for U+000C), never octal. The old decoder
    # dropped the backslash and emitted the bare letter, so the ZONE
    # rejection named `launcher/afb.py` — the wrong path. RED-first.
    weird = "launcher/a\x0cb.py"
    repo = _base(tmp_path, {weird: "x\n", "src/keep.py": "k\n"})

    def mutate(r):
        _git("mv", weird, "src/b.py", cwd=r)

    patch = _change_patch(repo, mutate)
    # mechanism fact (measured rendering): single backslash + 'f' bytes.
    assert rb'rename from "launcher/a\fb.py"' in patch
    v = _gate(patch)
    assert any("ZONE" in x and x.endswith("launcher/a\x0cb.py") for x in v), v


def test_git_unquote_named_control_escapes():
    # Unit claim (provenance: probe-r2b.py measured all five NAMED escapes
    # \a \b \v \f \r in real git renderings, 2026-10-19). The decoder must
    # map the full named set (plus \" and \\) to the byte values git
    # means. RED-first: the old map knew only n/t/"/\\ and passed the
    # letters through unchanged.
    quoted = '"A\\aB\\bC\\tD\\nE\\vF\\fG\\rH\\"I\\\\J"'
    expected = "A\x07B\x08C\tD\nE\x0bF\x0cG\rH\"I\\J"
    assert k8s._git_unquote(quoted) == expected


# --- 18: parser-environment failures — variant 2 (prepared, operator) -------
# Addendum prepared for the operator's decision 2026-10-19 ("Вариант 2
# принят к подготовке", решение — за оператором). Claim: the numstat
# parser's OWN environment can fail — mkdtemp (disk/quota) or the git
# subprocess (missing/broken binary) — and the core code lets those
# exceptions escape the gate (mkdtemp runs outside the try; the except
# catches only TimeoutExpired). A gate call must answer with a verdict,
# never raise. Honest framing (same as test 13): these monkeypatch the
# gate's own failure branches, not git behavior. RED-first against the
# core candidate: each of the three raises out of _gate.

_ONE_FILE = (b"diff --git a/src/x.py b/src/x.py\n--- /dev/null\n"
             b"+++ b/src/x.py\n@@ -0,0 +1 @@\n+x\n")


def test_numstat_mkdtemp_failure_is_parse_violation(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("mkdtemp: no space left on device")

    monkeypatch.setattr(k8s.tempfile, "mkdtemp", boom)
    v = _gate(_ONE_FILE)
    assert any("PATCH-PARSE" in x for x in v), v


def test_numstat_subprocess_oserror_is_parse_violation(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git binary not found")

    monkeypatch.setattr(k8s.subprocess, "run", fake_run)
    v = _gate(_ONE_FILE)
    assert any("PATCH-PARSE" in x for x in v), v


def test_numstat_oserror_after_mkdtemp_removes_temp_dir(monkeypatch):
    # Cleanup contract: the temp dir created BEFORE the failure must not
    # survive the call. Real mkdtemp, real directory lifecycle.
    created = []
    real_mkdtemp = k8s.tempfile.mkdtemp

    def spy(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        created.append(d)
        return d

    def fake_run(*args, **kwargs):
        raise OSError("git died")

    monkeypatch.setattr(k8s.tempfile, "mkdtemp", spy)
    monkeypatch.setattr(k8s.subprocess, "run", fake_run)
    v = _gate(_ONE_FILE)
    assert any("PATCH-PARSE" in x for x in v), v
    assert created, "mkdtemp spy never ran"
    assert all(not os.path.isdir(d) for d in created), created
