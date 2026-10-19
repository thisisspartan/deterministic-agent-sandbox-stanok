impl: src/preflight_demo.py
test: tests/test_preflight.py
run.sh: exists

# Sample 901 — BAD NAME (see README.md). `test_preflight.py` is test-like
# but matches no stack test_glob. Expected: rc 1, UNCLAIMED-TEST-NAME line.
