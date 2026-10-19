impl: src/ticketcheck_demo.py
test: tests/ticketcheck_demo_test.py
docs: docs/ticketcheck_demo.md
accept: none
run.sh: exists

# Sample 900 — GOOD (see README.md). Valid header in the pattern of a real
# launched ticket. Expected: rc 0, empty stdout. Declared
# paths deliberately do not exist: existence is the launch gate's business,
# not this checker's. `accept: none` is a legal header form (the parser's
# accept-none path); the sample originally self-referenced
# `accept: tests/ticketcheck_boundary_test.py` — that form became impossible
# after the 2026-10-20 relocation of the validator into launcher/ (the parser
# requires accept paths to pre-exist under tests/). See README.md and
# specs/SPEC-SELFHOST-TICKETCHECK.md amendment.
