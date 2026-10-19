impl: src/mod_demo.py
test: src/preflight_mod_test.py
run.sh: exists

# Sample 902 — BAD LOCATION (see README.md). Name matches the py glob, but
# the path is outside tests/ and the harness would never run it. Expected:
# rc 1, UNCLAIMED-TEST-PATH line.
