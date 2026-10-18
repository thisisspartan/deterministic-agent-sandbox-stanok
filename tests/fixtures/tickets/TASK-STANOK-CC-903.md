impl: src/dup_demo.py
test: tests/dup_demo_test.py
docs: docs/dup_demo.md
run.sh: exists

# Sample 903 — BAD DUPLICATE half 1/2 (see README.md). Same ticket number 903
# as TASK-STANOK-CC-903-dup.md. Expected: rc 1, DUPLICATE-TICKET-NUMBER
# line naming the other file.
