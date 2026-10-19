impl: src/malformed_demo.py
test: tests/bad name.py
run.sh: exists

# Sample 904 — MALFORMED HEADER (see README.md). The test: line carries a
# space and violates the strict header form: parse_ticket_header raises
# (would be rc=13 at launch). Expected: rc 2, PARSE on stderr.
