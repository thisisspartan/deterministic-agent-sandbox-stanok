"""ticketcheck — pre-flight validator for ticket headers (CC-296).

Checks a ticket file for EXACTLY the three error classes the existing gates
do not catch before a launch:

  1. UNCLAIMED-TEST-NAME — a test:/accept: basename no stack test_glob
     claims. Today this surfaces only post-run (`run.sh list` rc=1 /
     verify ACCEPTANCE NOT REGISTERED).
  2. UNCLAIMED-TEST-PATH — a test:/accept: path whose first component is
     not tests/. The launch gate accepts it (src/ etc. are writable zones),
     but the harness only discovers tests under tests/, so it is never run.
  3. DUPLICATE-TICKET-NUMBER — two .md files in one directory claiming the
     same (series, int(num)). Today it surfaces only when both launch.

Everything else (malformed headers, undeclarable paths, accept contradictions,
create-vs-edit, protected edits) is already caught by parse_ticket_header /
the launch gates — this tool does not duplicate those. The header is parsed
by the ONE contract parser, `launcher.ticket.parse_ticket_header` (cfg is a
shim exposing only repo_root); kinds are recovered with the same regex
tokens and the same loop structure, never a second grammar. Test-name
registry: the test_glob field of scripts/stacks/*.toml — the single source,
no hardcoded test-file names.

Usage: python3 -m src.ticketcheck <ticket-file> [<ticket-file> ...]
run from the repo root (repo_root = os.getcwd()); input paths are echoed
into messages exactly as given.

Output / exit codes:
  0  clean — empty stdout (zero input files is vacuously clean, the same
     convention run.sh uses for an empty suite)
  1  >=1 violation — stdout: VIOLATION lines (files in argv order; within a
     file: declared test:/accept: paths in header order, location check then
     name check, then the duplicate line)
  2  >=1 PARSE error — stderr: PARSE lines; a PARSE-failed file's rules are
     skipped, the other files are still processed; rc 2 takes priority over 1
"""

import fnmatch
import os
import re
import sys
import tomllib
import types

# The documented invocation is `python3 -m src.ticketcheck` from the repo
# root (repo root on sys.path). The run.sh smoke runner uses the direct form
# `python3 src/ticketcheck.py`, where sys.path[0] is src/ — make the repo
# root importable there too (a no-op for the -m/pytest forms, which already
# have it).
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_DIR not in sys.path:
    sys.path.insert(0, _REPO_DIR)

from launcher.ticket import (
    _ACCEPT_NONE_RE,
    _FILE_LINE_RE,
    _RESET_NONE_RE,
    parse_ticket_header,
)

# Ticket-file ID: <series>-<num>[-<suffix>].md — the collision key is
# (series, int(num)), so TASK-X-903-dup.md collides with TASK-X-903.md and
# zero-padded numbers collide with their unpadded form.
_TICKET_ID_RE = re.compile(r"^(?P<series>.+)-(?P<num>\d+)(?:-[A-Za-z0-9]+)?\.md$")

# The only header kinds this tool checks.
_CHECKED_KINDS = ("test", "accept")


def load_registry(repo_root: str) -> list[str]:
    """The test-name registry: the test_glob of every stack manifest under
    scripts/stacks/ — the single source (the same manifests run.sh derives
    its STACK REGISTRY from). Fail-closed: a manifest without a non-empty
    string test_glob, or no manifests at all, raises."""
    stacks_dir = os.path.join(repo_root, "scripts", "stacks")
    globs: list[str] = []
    for name in sorted(os.listdir(stacks_dir)):
        if not name.endswith(".toml"):
            continue
        with open(os.path.join(stacks_dir, name), "rb") as f:
            manifest = tomllib.load(f)
        glob = manifest.get("test_glob")
        if not isinstance(glob, str) or not glob:
            raise ValueError(f"ticketcheck: manifest {name} has no test_glob")
        globs.append(glob)
    if not globs:
        raise ValueError(f"ticketcheck: no stack manifests in {stacks_dir}")
    return globs


def _checked_declarations(text: str) -> list[tuple[str, str]]:
    """Recover the kinds of the checked declarations (test:/accept:).

    parse_ticket_header returns declared paths as a kind-less union, so the
    kinds are recovered with the SAME regex tokens (_FILE_LINE_RE,
    _ACCEPT_NONE_RE, _RESET_NONE_RE) and the SAME loop structure as the
    parser — no second grammar. Call this only after parse_ticket_header has
    validated the header, so a non-matching line simply ends the header."""
    entries: list[tuple[str, str]] = []
    seen_accept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _ACCEPT_NONE_RE.match(stripped):
            continue
        m = _FILE_LINE_RE.match(stripped)
        if m:
            kind, rel = m.group(1), m.group(2)
            if kind == "accept":
                if rel not in seen_accept:  # same dedup as the parser
                    seen_accept.append(rel)
                    entries.append((kind, rel))
            elif kind in _CHECKED_KINDS:
                entries.append((kind, rel))
            continue
        if _RESET_NONE_RE.match(stripped):
            continue
        break
    return entries


def _ticket_id(path: str) -> tuple[str, int] | None:
    m = _TICKET_ID_RE.match(os.path.basename(path))
    if not m:
        return None
    return (m.group("series"), int(m.group("num")))


def _duplicate_lines(ticket_file: str, repo_root: str) -> list[str]:
    """One line per input file naming the other file that claims the same
    (series, int(num)) — a .md in the SAME directory as this ticket file."""
    ticket_id = _ticket_id(ticket_file)
    if ticket_id is None:
        return []
    dirname = os.path.dirname(ticket_file)
    scan_dir = os.path.join(repo_root, dirname) if dirname else repo_root
    try:
        names = sorted(os.listdir(scan_dir))
    except OSError:
        return []
    own_base = os.path.basename(ticket_file)
    for name in names:
        if name == own_base or not os.path.isfile(os.path.join(scan_dir, name)):
            continue
        if _ticket_id(name) != ticket_id:
            continue
        other = os.path.join(dirname, name) if dirname else name
        return [f"VIOLATION DUPLICATE-TICKET-NUMBER: {ticket_file}: "
                f"ticket number {ticket_id[1]} also claimed by {other}"]
    return []


def check_ticket(ticket_file: str, repo_root: str,
                 registry: list[str]) -> tuple[list[str], list[str]]:
    """Check one ticket file. Returns (violation_lines, parse_lines).

    parse_lines is non-empty exactly when the file cannot be read or its
    header is rejected by parse_ticket_header — then the rules are skipped
    for that file. Messages echo ticket_file exactly as given. Existence of
    declared paths is NOT checked (assert_create_paths_are_new is the launch
    gate's business)."""
    try:
        with open(os.path.join(repo_root, ticket_file),
                  encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"PARSE: {ticket_file}: unreadable: {exc}"]
    cfg = types.SimpleNamespace(repo_root=repo_root)
    try:
        parse_ticket_header(cfg, text)
    except ValueError as exc:
        return [], [f"PARSE: {ticket_file}: invalid header: {exc}"]

    violations: list[str] = []
    for kind, rel in _checked_declarations(text):
        if rel.split("/")[0] != "tests":
            violations.append(
                f"VIOLATION UNCLAIMED-TEST-PATH: {ticket_file}: {kind} path "
                f"'{rel}': must live under tests/")
        base = os.path.basename(rel)
        if not any(fnmatch.fnmatchcase(base, glob) for glob in registry):
            violations.append(
                f"VIOLATION UNCLAIMED-TEST-NAME: {ticket_file}: {kind} path "
                f"'{rel}': basename '{base}' matches no stack test_glob")
    violations.extend(_duplicate_lines(ticket_file, repo_root))
    return violations, []


def main(argv: list[str] | None = None) -> int:
    """CLI entry: check every ticket file given. repo_root = os.getcwd()
    (the tool is run from the repo root). Exit: 0 clean, 1 violations,
    2 PARSE (priority over 1)."""
    files = list(sys.argv[1:] if argv is None else argv)
    # Zero input files: nothing to check — no violation, no PARSE -> 0
    # (same convention as run.sh: an empty suite passes, no output).
    if not files:
        return 0
    repo_root = os.getcwd()
    registry = load_registry(repo_root)
    parse_failed = False
    violations: list[str] = []
    for ticket_file in files:
        file_violations, parse_lines = check_ticket(
            ticket_file, repo_root, registry)
        for line in parse_lines:
            print(line, file=sys.stderr)
        if parse_lines:
            parse_failed = True
        violations.extend(file_violations)
    for line in violations:
        print(line)
    if parse_failed:
        return 2
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
