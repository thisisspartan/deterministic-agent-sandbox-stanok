# fire_main (TASK-STANOK-CC-242 / FIRE-03)

The runnable Doom fire: the main loop that ties `src/fire_engine.py` and
`src/fire_render.py` (imported, never modified) to a terminal — with FPS
timing, resize-safe geometry, and a guaranteed, idempotent teardown. All loop
dependencies are injectable, so the loop is fully testable without a real TTY.

## Contract

`src/fire_main.py`

- `FireApp(out, clock, size_fn=shutil.get_terminal_size)`
  - `out` — a sink with `.write(str)` (real app: `sys.stdout`).
  - `clock` — an object with `.perf_counter()` and `.sleep(s)` (real app: the
    `time` module).
  - `size_fn` — a callable returning `(cols, rows)`. Field geometry:
    `width = cols`, `height = rows * 2` — the renderer pairs two field rows
    per terminal row (half-block), so a field twice as tall as the terminal
    fills it exactly.
  - `wind` — attribute, default 0, passed to `field.step(wind)`.

- `run(fps=30, max_frames=None)`
  1. Installs signal handlers (SIGINT/SIGTERM → request stop; SIGWINCH → set
     resize flag) and registers `teardown` with `atexit`.
  2. Writes `fire_render.ENTER` exactly once.
  3. Loop, while not stopped and (if given) `frames < max_frames`:
     - **tick start:** if the resize flag is set, clear it and rebuild the
       field from a fresh `size_fn()` call — geometry is recomputed ONLY here,
       never inside step/render, so a resize can never tear a frame mid-render
       (no IndexError).
     - `field.step(wind)`; then exactly **one** `out.write(render_frame(field))`
       per frame.
     - **delta-time compensation:** absolute frame deadlines —
       `next_at += 1/fps`; after the frame, `sleep(max(0, next_at - now))` via
       the injected clock. A slow frame borrows from the next budget instead
       of drifting the whole schedule; no sleep is issued when already behind.
  4. `finally: teardown()` — returns cleanly.

- `teardown()` — GUARANTEED (reached via `finally`, `atexit`, and the
  SIGINT/SIGTERM stop path) and IDEMPOTENT: writes `fire_render.EXIT` exactly
  once total; every later call is a no-op. Restores the previous signal
  handlers.

- Signal handlers: SIGINT/SIGTERM only set the stop flag (checked at the loop
  head); SIGWINCH only sets the resize flag — no buffer work in any handler.

- `parse_fps(argv=None) -> int` — `--fps N`, default 30.
- `main()` — builds the real app (`sys.stdout`, `time`,
  `shutil.get_terminal_size`) and runs it. `if __name__ == "__main__": main()`.

## Why injectable

The loop reads time only through `clock`, writes only through `out`, and reads
geometry only through `size_fn`. Tests pin all three (fake clock with a fixed
per-read overhead, recording sink, mutable fake size) and assert the exact
sleep sequence, the ENTER/EXIT counts, one write per frame, and the resize
applied at the next tick start.

## Tests

`tests/fire_main_test.py` (pytest, run via
`scripts/run.sh test tests/fire_main_test.py`)

- ENTER exactly once / EXIT exactly once for a bounded run; exactly one
  `out.write` per frame, each a valid render frame.
- Teardown idempotency: explicit double calls; stop via the real SIGINT
  handler path; via SIGTERM; via an exception raised inside `step` — in all
  four the EXIT appears exactly once.
- Resize: `size_fn` changes between frames + SIGWINCH → new geometry applied
  at the next tick start (frame cell counts change exactly there), no
  IndexError, the original frame count is preserved; the WINCH handler itself
  touches no buffers.
- Delta-time: with a pinned fake clock every sleep equals `1/fps − overhead`;
  no sleep when a frame is already behind budget; a custom `--fps` scales the
  budget.
- `parse_fps`: default 30, `--fps 60` honored.
