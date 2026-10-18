impl: src/ticketcheck_demo.py
test: tests/ticketcheck_demo_test.py
docs: docs/ticketcheck_demo.md
accept: tests/ticketcheck_boundary_test.py
run.sh: exists

# Sample 900 — GOOD (see README.md). Valid header in the pattern of a real
# launched ticket (CC-295-style). Expected: rc 0, empty stdout. Declared
# paths deliberately do not exist: existence is the launch gate's business,
# not this checker's.
