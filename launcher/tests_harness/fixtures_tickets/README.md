# launcher/tests_harness/fixtures_tickets — signed frozen ticket samples for ticketcheck

Input samples for the pre-flight validator `launcher/ticketcheck.py`
(specs/SPEC-SELFHOST-TICKETCHECK.md §3). They are tracked here because the
live `tickets/` dir and `evidence/` of the parent repo do NOT reach the Pod
(transport = `git archive HEAD` = tracked tree only).

Each sample is signed: what is bad, which rule catches it, expected rc and
exact stdout. Headers are mutations of REAL ticket headers: the scan of the
live ticket corpus at authoring time (2026-10-18) found zero violations of
these rules, so historical bad samples do not exist — the bad samples are
honestly synthetic mutations, signed below.
Synthetic numbers 900+ are outside the live ticket-number range. Privacy: no
IPs, no home paths (this dir is published with the repo).

Limitation: frozen samples prove behavior on past garbage only; a new error
class gets a new signed sample per incident.

Files here live under `launcher/` — outside the machine's writable zones:
the zone rule (launcher/zones.py, rc=13 at header parse) refuses a ticket
declaring them, the tool deny-list in `.claude/settings.stanok.json` denies
Read/Edit/Write under `launcher/**` inside the Pod, and only
`src/ tests/ docs/ scripts/run.sh` ever reach the host's patch gate — so a
ticket may not create, modify or delete them. Before the 2026-10-20
relocation they were `tests/**` — protected the same way (contract lock). Run all ticketcheck calls with
`cwd = repo root` and the relative paths exactly as listed (the tool echoes
the input path into its messages).

| file | what is bad | rule that catches it | expected rc / stdout |
|---|---|---|---|
| TASK-STANOK-CC-900.md | nothing — valid header (pattern of a real launched ticket with `accept: none`). Amendment 2026-10-20: the sample previously declared `accept: tests/ticketcheck_boundary_test.py` (self-reference to the boundary test); after the validator's relocation into launcher/ that form is impossible — the parser requires accept paths to pre-exist under tests/ (launcher/ticket.py:248-255) | — | 0, empty |
| TASK-STANOK-CC-901.md | `test:` name `test_preflight.py` is test-like but matches no stack test_glob; post-run analog: `run.sh list` rc=1 / verify.py ACCEPTANCE NOT REGISTERED | UNCLAIMED-TEST-NAME | 1, `VIOLATION UNCLAIMED-TEST-NAME: launcher/tests_harness/fixtures_tickets/TASK-STANOK-CC-901.md: test path 'tests/test_preflight.py': basename 'test_preflight.py' matches no stack test_glob` |
| TASK-STANOK-CC-902.md | `test:` path under src/ — legal for the pre-Pod path gate (src is a writable zone) but never run by the harness (registry claims only `find tests`) | UNCLAIMED-TEST-PATH | 1, `VIOLATION UNCLAIMED-TEST-PATH: launcher/tests_harness/fixtures_tickets/TASK-STANOK-CC-902.md: test path 'src/preflight_mod_test.py': must live under tests/` |
| TASK-STANOK-CC-903.md + TASK-STANOK-CC-903-dup.md | same ticket number 903 claimed by two files in one directory (series TASK-STANOK-CC) | DUPLICATE-TICKET-NUMBER | 1, one line per input file naming the other (see the two exact lines in the boundary test) |
| TASK-STANOK-CC-904.md | malformed header line `test:` with a space — ValueError in parse_ticket_header (would become rc=13 at launch) | PARSE | 2, stderr `PARSE: launcher/tests_harness/fixtures_tickets/TASK-STANOK-CC-904.md: invalid header: ...` |
