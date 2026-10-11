# bash_smoke — in-Pod live proof that the Bash tool and its tmp root work

Module: `src/bash_smoke.py` (stdlib only: `os`, `secrets`, `subprocess`).
Tests: `tests/bash_smoke_test.py`. Ticket: TASK-STANOK-CC-234.

## Why

Incident cc231/cc233: under the Pod's read-only root filesystem the CLI Bash
tool's tmp root (`(CLAUDE_CODE_TMPDIR || "/tmp")/claude-<uid>`) was
unwritable — every Bash call died with ENOENT, the agent wrote blind, and the
host verdict was still PASS. The runtime was fixed host-side: both runner Pods
mount a writable emptyDir at `/tmp` and set `CLAUDE_CODE_TMPDIR` to it. This
module computes, from inside the Pod, the facts that prove the fix holds.

## Contract

- `tmp_root() -> str` — the directory the CLI Bash tool uses: the value of the
  environment variable `CLAUDE_CODE_TMPDIR` if set, otherwise `"/tmp"`. Read
  from the environment at call time (never cached).
- `probe() -> dict` — facts about the current environment, all computed, never
  hardcoded:
  - `"tmp_root"` (str): the resolved tmp root path, equal to `tmp_root()`.
  - `"tmp_root_writable"` (bool): `True` if a uniquely-named file
    (`bash-smoke-<hex>`) can be created and removed inside the tmp root; any
    `OSError` (EROFS/EPERM/ENOENT) -> `False`.
  - `"claude_dir_ok"` (bool): `True` if `<tmp_root>/claude-<uid>` (uid from
    `os.getuid()`) can be CREATED — as the CLI Bash tool itself does, not a
    pre-existing directory — and a uniquely-named file can be created and
    removed inside it; any `OSError` -> `False`. The fresh-check Pod runs no
    CLI session, so nothing creates the directory there: the invariant is that
    it CAN be created and written.
  - `"bash_runs"` (bool): `True` if `subprocess.run(["bash", "-c", "pwd"])`
    exits 0; `False` on a non-zero exit or when bash cannot be executed.

## Test mapping

- `test_tmp_root_resolution` — runs everywhere: `CLAUDE_CODE_TMPDIR` set ->
  that value; unset -> `"/tmp"` (environment monkeypatched).
- `test_probe_shape` — runs everywhere: all four keys present with the right
  types; `probe()["tmp_root"] == tmp_root()`.
- `test_tmp_root_writable_in_pod` — Pod-only (`skipif` on `STANOK_IN_POD`,
  same pattern as `tests/pod_guard_test.py`): `tmp_root_writable is True` and
  `claude_dir_ok is True`.
- `test_bash_runs_in_pod` — Pod-only: `bash_runs is True`.
