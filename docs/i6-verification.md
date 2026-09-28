# I6 verification: LOG_DIR hidden from the sandbox (TASK-STANOK-CC-173)

Empirical probe of the log/evidence directory performed from inside the
sandboxed Bash on 2026-09-28. Every exit code and error text below is the REAL
observed value (not invented).

## Probed path

`/tmp/stanok-logs` — `$STANOK_LOG_DIR` was unset, so the fallback path was used.

The sandbox config (`.claude/settings.stanok.json`) declares this path in BOTH
`denyWrite` and `denyRead`. The probes below check whether that deny is actually
enforced from the inside.

## Probe a — `ls` of the path

- Command: `ls /tmp/stanok-logs`
- Exit code: `0`
- stdout: (empty)
- stderr: (empty)

Interpretation: the directory IS listable (exit 0, no error). Under a working
deny this would be expected to fail with a non-zero exit / permission error.

## Probe b — create a probe file inside it

- Command: `touch /tmp/stanok-logs/probe-<PID>-i6.txt`
- Exit code: `0`
- stdout: (empty)
- stderr: (empty)

Interpretation: the write did NOT fail (exit 0, no EROFS / EACCES / ENOTDIR).
Under a working deny this would be expected to fail with a non-zero exit and an
error such as "Read-only file system" or "Permission denied".

Anomaly: although `touch` returned exit 0, the probe file was NOT actually
persisted — a subsequent `ls -la /tmp/stanok-logs/` shows the directory still
empty (only `.` and `..`). The sandbox reports success without blocking or
persisting the write (fail-open behavior).

## Probe c — read it as a directory

- Command: `python3 -c "import os; print(os.path.isdir('/tmp/stanok-logs'))"`
- Exit code: `0`
- stdout: `True`
- stderr: (empty)

Interpretation: the path IS seen as a directory. Under a working deny this would
be expected to be `False` (or raise a read error).

## Reference test

`bash scripts/run.sh test tests/test_adversarial_test.py` → **exit 1**
(reproduced twice). `test_logdir_not_writable` FAILS with:

```
AssertionError: isolation gap: sandboxed process CAN write to its own log dir:
path=/tmp/stanok-logs error=None
assert True is False
```

(`writable=True`.) The other 3 tests in the file pass.

## Verdict

NO — the log dir is NOT inaccessible from the sandbox: `ls` succeeds (dir
listable), the write probe did NOT fail (exit 0), `os.path.isdir` is `True`, and
the reference test `test_logdir_not_writable` FAILS. The I6 fix (denyWrite +
denyRead on `/tmp/stanok-logs`) is declared in the config but is NOT being
enforced from the inside.
