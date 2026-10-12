# fire_main — the runnable main loop

Module: `src/fire_main.py` (TASK-STANOK-CC-250, FIRE2-03). Uses
`src/fire_engine.py` (`FireField`) and `src/fire_render.py` (`ENTER`, `EXIT`,
`render_frame`) as they are; neither is modified.

## Contract

- `class FireApp(out=None, clock=None, size_fn=None, wind=0, keys=None)` —
  every dependency is injectable, so the loop is testable without a real
  terminal:
  - `out` — a sink with `write(str)` (default `sys.stdout`);
  - `clock` — an object with `perf_counter()` and `sleep(s)` (default the
    `time` module);
  - `size_fn` — returns `(cols, rows)` (default `shutil.get_terminal_size`);
  - `wind` — passed to `field.step(wind)` (default 0);
  - `keys` (FIRE2-04, `src/fire_input.py`) — optional source with
    `.read()` returning an action or `None`; polled **once per tick,
    before step**: `wind_left`/`wind_right` move `wind` clamped to
    `[-WIND_LIMIT, WIND_LIMIT]`; `intensity_up`/`intensity_down` adjust a
    decay level applied to every field value before step (`value -= 1` per
    level, clamped ≥ 0 — documented choice: `FireField.step` has no
    intensity parameter); `"quit"` requests a stop through the same path
    as SIGINT. `keys=None` (the default) changes nothing.
- Geometry: the field is `cols` wide and `rows * 2` tall — the renderer is
  half-block, so one terminal row covers two field rows.
- `run(fps=30, max_frames=None)`:
  1. writes `fire_render.ENTER` once;
  2. builds the field, then loops: **if a resize flag is set, recompute
     dimensions/buffer at TICK START only** (never inside step/render) →
     poll `keys` once and apply the action (when `keys` is not None) →
     `field.step(wind)` → **exactly one** `out.write(render_frame(field))`;
  3. delta-time compensation: `elapsed = perf_counter() - tick_start`,
     `sleep(1/fps - elapsed)` — and only when the frame underran its budget;
  4. `max_frames` bounds the loop (tests); `fps <= 0` raises `ValueError`
     before anything is written; returns cleanly.
- Signals (installed for the duration of a run, previous handlers restored by
  teardown): `SIGINT`/`SIGTERM` → `handle_stop` requests a stop; `SIGWINCH` →
  `handle_winch` **sets a flag only** — no dimensions, no buffer work in the
  handler. A resize is applied at the next tick start; the frame count is not
  reset by it.
- `teardown()` — guaranteed (the `finally` in `run`, plus `atexit.register`
  plus the signal handlers) and idempotent: writes `fire_render.EXIT` exactly
  once per run, and only if `ENTER` was written. Extra calls are no-ops; the
  write is guarded so teardown never raises from `atexit`.
- `main()` — parses `--fps N` (default 30), builds the real app
  (`sys.stdout`, `time`, `shutil.get_terminal_size`) and runs it; creates a
  `KeyReader` on stdin **only when `sys.stdin.isatty()`** (non-tty runs —
  CI, pipes — keep `keys=None`) and closes it after the run;
  `if __name__ == "__main__": main()`.

## Tests

`tests/fire_main_test.py` (pytest, via `scripts/run.sh test ...`) drives the
loop with a fake sink / fake clock / fake size_fn: ENTER and EXIT exactly once;
one write per frame and frame geometry == requested size; field height ==
rows*2; teardown idempotency after a run, after a stop requested through the
installed SIGINT and SIGTERM handlers (delivered with `os.kill`), and after an
exception raised in `step`; handlers installed during the run and restored
after it; the SIGWINCH handler touches no buffers; a resize between frames is
applied at the next tick start with no IndexError and the frame count
preserved; the sleep sequence for a pinned fake clock (full budget, partial
budget, overrun → no sleep); `fps` sets the budget and rejects `fps <= 0`; and
two subprocess tests run the real program and assert a graceful exit (rc 0)
with ENTER once and EXIT once on SIGINT and SIGTERM.
