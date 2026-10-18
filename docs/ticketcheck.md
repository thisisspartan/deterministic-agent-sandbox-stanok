# ticketcheck — module contract (CC-296)

Pre-flight validator for ticket headers. It checks EXACTLY the three error
classes the existing gates do not catch before a launch — nothing else is
duplicated (malformed headers, undeclarable paths, accept contradictions,
create-vs-edit, protected edits stay the business of `parse_ticket_header`
and the launch gates).

Why these three are the gap:

- **names** — an unclaimed test basename is only discovered post-run
  (`run.sh list` rc=1 / verify `ACCEPTANCE NOT REGISTERED`);
- **collisions** — a duplicated ticket number only surfaces when both
  tickets launch;
- **paths** — a `test:` path outside `tests/` passes the launch gate
  (src/ etc. are writable zones) but the harness only discovers tests under
  `tests/`, so it is silently never run.

Invocation: `python3 -m src.ticketcheck <ticket-file> [<ticket-file> ...]`
from the repo root (`repo_root = os.getcwd()`); input paths are echoed into
messages exactly as given. Stdlib only; the network is not used.

Tests: `bash scripts/run.sh test tests/ticketcheck_test.py` (unit, in-process
API over tmp_path mini-trees) and `tests/ticketcheck_boundary_test.py`
(host-authored subprocess boundary over the frozen samples in
`tests/fixtures/tickets/`).

## API (names pinned)

```
load_registry(repo_root) -> list[str]
check_ticket(ticket_file, repo_root, registry) -> (violations, parse_lines)
main(argv=None) -> int
```

- `load_registry` — the test-name registry: the `test_glob` field of every
  `scripts/stacks/*.toml` manifest (tomllib) — the single source; no
  test-file names are hardcoded. Fail-closed: a manifest without a non-empty
  string `test_glob`, or no manifests, raises.
- `check_ticket` — one file: read → parse → rules. Returns
  `(violation_lines, parse_lines)`; `parse_lines` is non-empty exactly when
  the file is unreadable or `parse_ticket_header` rejects the header — then
  the rules are skipped for that file.
- `main` — the CLI over argv (default `sys.argv[1:]`).

## Parsing — the ONE contract parser

The header is parsed by `launcher.ticket.parse_ticket_header` (cfg is a
`types.SimpleNamespace(repo_root=...)` shim; the parser uses cfg only for
repo_root). A standalone header parse is forbidden. Kinds (only `test:` /
`accept:` are needed) are recovered with the same regex tokens
(`_FILE_LINE_RE`, `_ACCEPT_NONE_RE`, `_RESET_NONE_RE`) and the same loop
structure — no second grammar. `assert_create_paths_are_new` is NOT called:
existence of declared paths is the launch gate's competence.

## Rules (only test:/accept: paths; impl:/docs:/edit: are never checked)

1. **UNCLAIMED-TEST-PATH** — first path component ≠ `tests`:
   `VIOLATION UNCLAIMED-TEST-PATH: <ticket-file>: <kind> path '<rel>': must live under tests/`
2. **UNCLAIMED-TEST-NAME** — basename matches no stack `test_glob`
   (`fnmatch.fnmatchcase`):
   `VIOLATION UNCLAIMED-TEST-NAME: <ticket-file>: <kind> path '<rel>': basename '<base>' matches no stack test_glob`
3. **DUPLICATE-TICKET-NUMBER** — ticket-file ID
   `^(?P<series>.+)-(?P<num>\d+)(?:-[A-Za-z0-9]+)?\.md$`; a collision is
   another `.md` file in the SAME directory with the same `(series,
   int(num))` (so `-alt` suffixes and zero-padded numbers collide). One line
   per input file, naming the other file (argv-relative path):
   `VIOLATION DUPLICATE-TICKET-NUMBER: <ticket-file>: ticket number <n> also claimed by <other>`

The rules are independent: a good-name+bad-location path yields only the
location line, a bad-name+good-location path only the name line; a path
violating both yields both lines.

## PARSE errors

- unreadable file → `PARSE: <ticket-file>: unreadable: <error>` (stderr);
- `ValueError` from the parser (malformed header, accept contradictions) →
  `PARSE: <ticket-file>: invalid header: <error text>` (stderr).

## Line order and exit codes

Order: files in argv order; within a file — declared test:/accept: paths in
header order (per path: location check, then name check), then the duplicate
line. A PARSE-failed file skips its own rules; the other files are still
processed.

- `0` — clean, empty stdout (zero input files is vacuously clean, the same
  convention run.sh uses for an empty suite);
- `1` — ≥1 violation: stdout = the VIOLATION lines;
- `2` — ≥1 PARSE: the PARSE lines on stderr; priority over 1 (violations of
  the files that did parse are still printed to stdout).
