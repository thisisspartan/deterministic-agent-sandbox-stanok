"""patchgate — the host-side patch verification layer (wave A portion 4,
2026-10-21; names and bodies moved VERBATIM from launcher/k8s.py).

The cluster is the patch's contract check: identity (SHA-256 of the exact
bytes, strict decode), transport-layer zone gate (numstat-sourced paths,
allow-list zones.WRITABLE_ZONES, absolute/'..'/'.git' forms, symlink/gitlink
REJECT-always), and the on-disk re-verification. It answers "zone?"; the
manifest comparison (verify._compare_manifests, reached by k8s through
scratch_contract_violations) answers "declared/protected?" — the two checks
stay separate.

Strict from birth (mypy.ini per-module section): the moved functions carried
k8s strict-class debt, so their signatures are annotated AT move time
(bare `list` -> `list[str]`); bodies unchanged.
Single patch home: k8s holds no def and no re-export of these names; the
remaining k8s code calls them as `patchgate._X`, so a test stub on a name
here intercepts every call site. _live_tree_drift / apply_patch_scratch /
scratch_contract_violations stay in k8s for now (transport+contract
machinery — a later portion). Guard: test_patchgate_facade.py
(RED-calibrated). Acceptance: behavioral reference byte-identical
(evidence/waveA-ref-* recipe: run with a nonexistent ticket -> rc=13).
"""

import hashlib
import re
import shutil
import subprocess
import tempfile

from launcher import zones

_DIFF_HEADER_PREFIX = "diff --git "
_OLDNEW_RE = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?(\S+)")
_RENAME_COPY_RE = re.compile(r"^(?:rename|copy) (?:from|to) (.+)")
_MODE_SYMLINK_RE = re.compile(
    r"^(old mode|new(?: file)? mode|deleted(?: file)? mode) 120000", re.M)
# measured rendering (probe-r2.py): relinking an existing symlink produces
# NO mode line — the 120000 mode appears only on the `index … 120000`
# line, exactly as git renders gitlinks as `index … 160000`.
_INDEX_SYMLINK_RE = re.compile(r"^index \S+ 120000")
_MODE_GITLINK_RE = re.compile(
    r"^(old mode|new(?: file)? mode|deleted file mode) 160000", re.M)
_INDEX_GITLINK_RE = re.compile(r"^index \S+ 160000")
_SUBPROJECT_RE = re.compile(r"^Subproject commit ")


def _path_violations(path: str) -> list[str]:
    """One path, every transport invariant (Package 1, operator spec
    2026-10-10): no absolute path, no '..' segment, no '.git' component
    (the .git directory is the machine's read-only boundary — a patch that
    touches it bypasses every src/tests/docs rule; .gitignore is a normal
    file, only the exact '.git' component is rejected). /dev/null is the
    git sentinel for add/delete, not a path."""
    if path == "/dev/null":
        return []
    violations = []
    if path.startswith("/"):
        violations.append(f"ABSOLUTE: {path}")
    segments = path.split("/")
    if ".." in segments:
        violations.append(f"TRAVERSAL: {path}")
    if ".git" in segments:
        violations.append(f"GITDIR: {path}")
    return violations


def _git_unquote(path: str) -> str:
    """Undo git's C-style path quoting: rename/copy endpoints for unusual
    names arrive quoted, and the endpoint check must judge the SAME decoded
    path that `git apply --numstat` reports, not the quoted text. Two
    escape forms exist and both must decode: octal byte escapes for
    non-ASCII bytes (`"docs/non\\303\\244scii"`), and NAMED escapes for
    control characters — git writes `\\a \\b \\t \\n \\v \\f \\r`, never
    octal (measured, probe-r2b.py 2026-10-19). Dropping the backslash and
    emitting the bare letter instead names a WRONG path."""
    path = path.strip()
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    body = path[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.extend(c.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= len(body):
            break
        n = body[i]
        if n in "01234567":
            digits = body[i:i + 3]
            j = 0
            while j < 3 and j < len(digits) and digits[j] in "01234567":
                j += 1
            out.append(int(digits[:j], 8))
            i += j
        else:
            out.extend({"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\",
                        "a": b"\a", "b": b"\b", "v": b"\v", "f": b"\f",
                        "r": b"\r"}.get(n, n.encode("utf-8")))
            i += 1
    return out.decode("utf-8", "surrogateescape")


def _numstat_paths(patch_text: str) -> list[str] | None:
    """The machine-sourced path list (wave C, TASK-NEXT §7): `git apply
    --numstat -z` run in an empty temp dir is a pure parser — no tree is
    needed, quoted/spaced/non-ASCII names arrive RAW (the regex headers could
    never represent them), and one entry is produced per file section in
    patch order (rename/copy: the DESTINATION only — sources live in the
    headers). rc != 0 (corrupt patch, invalid mode) -> None: the caller
    reports PATCH-PARSE, fail closed.

    Variant 2 (prepared for operator decision 2026-10-19; "Вариант 2
    принят к"): the parser's OWN environment can fail — mkdtemp (disk,
    quota) or the git subprocess (missing/broken binary) — and a gate
    call must answer with a verdict, never raise. mkdtemp runs INSIDE
    the try; any OSError there is a parser-environment failure -> None.
    The `work = None` sentinel and the `if work is not None` guard are
    load-bearing on the measured runtimes: python 3.13.13 (host venv)
    raises TypeError on rmtree(None) while 3.11.2/3.12.3 do not
    (measured 2026-10-19) — without the guard a mkdtemp failure would
    replace the verdict with a different exception in the finally."""
    work = None
    try:
        work = tempfile.mkdtemp(prefix="stanok-numstat-")
        p = subprocess.run(
            ["git", "apply", "--numstat", "-z", "--unidiff-zero",
             "--allow-empty"],
            cwd=work, input=patch_text.encode("utf-8"),
            capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
    if p.returncode != 0:
        return None
    paths = []
    for rec in p.stdout.split(b"\0"):
        if not rec:
            continue
        parts = rec.split(b"\t", 2)
        if len(parts) != 3:
            return None
        paths.append(parts[2].decode("utf-8", "surrogateescape"))
    return paths


def _zone_violation(path: str) -> list[str]:
    """Allow-list, not deny-list (Saltzer–Schroeder fail-safe defaults,
    complete mediation): a path may be touched only when its FIRST component
    is a writable zone DIRECTORY and the path continues under it — MEMBERSHIP
    of the first component, never a string prefix (`srcx/a.py`, `docs_evil/…`
    are not `src`/`docs`), and a single-segment path is a root FILE named
    like a zone, not a file inside that zone. The single literal
    `zones.WRITABLE_ZONES` the ticket parser already uses is the allow-list;
    everything else is REJECT; no pattern list can enumerate it."""
    head, sep, _rest = path.partition("/")
    if not (sep and head in zones.WRITABLE_ZONES):
        return [f"ZONE: {path}"]
    return []


def patch_gate(patch_text: str) -> list[str]:
    """The transport-layer zone gate (re-assertion of the Docker-era
    invariants, rc=13/SEC-01; hardened by Package 1 2026-10-10; allow-list
    per the wave C spec 2026-10-19). Paths come from the MACHINE —
    `git apply --numstat -z` — not from regexes over the diff text: every
    parsed path and both rename/copy endpoints must pass the zone
    allow-list and the absolute/'..'/'.git' form checks; symlinks (120000
    in every mode form, and the `index … 120000` line a content relink
    renders without any mode line) and gitlinks (160000 in any mode form,
    the `index .. 160000` line, 'Subproject commit' lines) are
    REJECT-always, attributed to the exact parsed path. The text is split
    on \\n only — the same separator git uses — so content bytes cannot
    fabricate headers. A patch git cannot parse, or whose `diff --git`
    header count and parsed-path count do not match one-for-one, is
    PATCH-PARSE (fail closed). This gate answers "zone?"; the manifest comparison
    answers "declared/protected?" — the two checks stay separate.
    Rejected BEFORE apply — a host-issued CONTRACT-FAIL, never a silent
    apply."""
    paths = _numstat_paths(patch_text)
    if paths is None:
        return ["PATCH-PARSE: git could not parse the patch"]
    # split on \n ONLY (operator item 2026-10-20): git treats \n as the
    # line separator and lets content bytes through; str.splitlines() also
    # splits on \x0c, U+2028 and friends, so a content line carrying them
    # would fabricate a phantom `diff --git` header and the header<->path
    # count check would reject a genuine patch (measured, probe-r2.py).
    n_headers = sum(1 for line in patch_text.split("\n")
                    if line.startswith(_DIFF_HEADER_PREFIX))
    if n_headers != len(paths):
        return [f"PATCH-PARSE: {n_headers} file headers vs {len(paths)} "
                f"parsed paths"]
    violations = []
    section = 0
    current = None
    for line in patch_text.split("\n"):
        if line.startswith(_DIFF_HEADER_PREFIX):
            current = paths[section]
            section += 1
            continue
        m = _OLDNEW_RE.match(line)
        if m:
            violations.extend(_path_violations(m.group(1)))
            continue
        m = _RENAME_COPY_RE.match(line)
        if m:
            endpoint = _git_unquote(m.group(1))
            violations.extend(_path_violations(endpoint))
            violations.extend(_zone_violation(endpoint))
            continue
        if ((_MODE_SYMLINK_RE.match(line) or _INDEX_SYMLINK_RE.match(line))
                and current):
            violations.append(f"SYMLINK: {current}")
        elif (_MODE_GITLINK_RE.match(line) or _INDEX_GITLINK_RE.match(line)
                or _SUBPROJECT_RE.match(line)):
            violations.append(f"GITLINK: {current or '<no file header>'}")
    for path in paths:
        violations.extend(_path_violations(path))
        violations.extend(_zone_violation(path))
    return list(dict.fromkeys(violations))


def patch_sha256(patch_bytes: bytes) -> str:
    """The patch identity (Package 1): SHA-256 of the EXACT patch bytes,
    computed once from the payload; every later use of the patch (scratch
    apply, fresh Job, live apply) is re-verified against this hash —
    fail closed on mismatch."""
    return hashlib.sha256(patch_bytes).hexdigest()


def strict_patch_text(patch_bytes: bytes) -> str:
    """Decode the patch bytes STRICTLY (encoding-gap micro-patch, operator
    review 2026-10-10): the gate, the scratch contract and the apply must
    see exactly the text whose bytes are hashed and applied —
    errors="replace" would substitute U+FFFD and the contract would be
    verified against a tree different from the one that lands. Raises
    UnicodeDecodeError; the caller fail-closes with a host-issued
    CONTRACT-FAIL before any scratch/fresh/apply operation."""
    return patch_bytes.decode("utf-8")


def patch_identity_ok(patch_file: str, expected: str) -> bool:
    """Re-verify the on-disk patch file against the recorded hash."""
    try:
        with open(patch_file, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest() == expected
    except OSError:
        return False
