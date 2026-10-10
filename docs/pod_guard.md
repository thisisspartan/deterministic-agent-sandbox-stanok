# pod_guard (TASK-STANOK-CC-233)

In-Pod proof that the Pod-only test guard (CC-232) is active in both runner
Pods (worker and fresh-check). Stdlib only: `os`, `secrets`.

## Contract

`src/pod_guard.py`

- `in_pod() -> bool`
  `True` when the environment variable `STANOK_IN_POD` equals exactly `"1"`;
  `False` when it is absent or holds any other value. The marker is read from
  the environment at call time (so it can be monkeypatched in tests). Both
  runner Job templates set `STANOK_IN_POD=1`; the host sets nothing.

- `write_ok(path) -> bool`
  `True` when a uniquely-named probe file (`pod-guard-<token_hex(8)>`) can be
  created and removed inside the directory `path`; `False` when the attempt
  raises any `OSError` (`EROFS`/`EPERM`, or the directory does not exist). The
  probe file is always removed; nothing is left behind.

## Tests

`tests/pod_guard_test.py` (pytest, run via `scripts/run.sh test tests/pod_guard_test.py`)

- `test_in_pod_marker_parsing` — runs everywhere: the environment is
  monkeypatched; unset -> `False`, `"1"` -> `True`, `"0"` -> `False`.
- `test_marker_present_in_pod` — Pod-only (`skipif` on `STANOK_IN_POD`, the
  same pattern as `tests/ro_root_smoke_test.py`): `in_pod() is True`, i.e. the
  marker really is present in the running Pod.
- `test_work_zone_writable` — Pod-only: `write_ok("/stanok-work") is True`,
  i.e. the emptyDir designated writable zone accepts writes.

Outside the Pod the two Pod-only tests are skipped; the marker-parsing test
always runs.
