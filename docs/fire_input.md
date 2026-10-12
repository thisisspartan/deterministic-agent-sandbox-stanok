# fire_input — non-blocking raw-mode keyboard input

Module: `src/fire_input.py` (TASK-STANOK-CC-251, FIRE2-04). Consumed by
`src/fire_main.py` (`FireApp.keys`, `main()`); the engine and renderer are
untouched.

## Contract

- `parse_key(data: bytes) -> str | None` — pure exact-sequence lookup:
  - `b"\x1b[D"` → `"wind_left"`, `b"\x1b[C"` → `"wind_right"`,
    `b"\x1b[A"` → `"intensity_up"`, `b"\x1b[B"` → `"intensity_down"`,
    `b"q"` / `b"\x03"` → `"quit"`;
  - anything else — empty input, partial sequences, unknown bytes,
    multi-byte noise — → `None`. Non-bytes input → `None`.
- `class KeyReader(fd)`:
  - construction: if `fd` is a tty, the termios state is saved and the fd
    is set to raw mode (`termios.tcgetattr` + `tty.setraw`); a non-tty fd
    (pipe, /dev/null) is left untouched — `read()` still works (this is
    what the tests use);
  - `read() -> str | None` — **never blocks**: `select.select([fd], [],
    [], 0)` first; no data → `None`. If select reports readability,
    `os.read` cannot block; `BlockingIOError` (EAGAIN), `InterruptError`,
    other `OSError` and EOF all yield `None`. At most `MAX_READ` (64)
    bytes are drained per poll and parsed as one key event (a chunk that
    is not exactly one known sequence → `None`);
  - `close()` — restores the saved termios state (`TCSADRAIN`),
    idempotent; also usable as a context manager. After `close()`,
    `read()` returns `None`.

## Wiring (in src/fire_main.py)

`FireApp(keys=...)` polls `keys.read()` once per tick, **before** `step`,
and applies: `wind_left`/`wind_right` move `app.wind` clamped to
`[-WIND_LIMIT, WIND_LIMIT]` (the engine clamps too); `intensity_up`/
`intensity_down` adjust a decay level applied to every field value before
step (`value -= 1` per level, clamped ≥ 0 — documented choice, since
`FireField.step` has no intensity parameter); `"quit"` requests a stop
through the same path as SIGINT (teardown still exactly once). `keys=None`
(the default) changes nothing. `main()` creates a `KeyReader` on stdin only
when `sys.stdin.isatty()`, so non-tty runs (CI, pipes) keep the previous
behavior; the reader is closed after the run.

## Tests

`tests/fire_input_test.py` (pytest, via `scripts/run.sh test ...`): every
sequence maps to its exact action and unknown/multi-byte noise to `None`;
on an empty `os.pipe()` fd `read()` returns `None` immediately (measured
elapsed < 1 s — no sleep trick); a key written to the pipe is parsed; EOF
and noise are `None`; on a `pty.openpty()` slave raw mode is applied and
restored by `close()` (idempotently); the wiring is driven with fake
keys/sink/clock and a spy field: `keys=None` changes nothing, `wind_right`
raises the wind passed to `step` (applied before the first step), wind is
clamped to ±3, intensity levels accumulate and clamp at 0 (observed as
extra decay on the seeded source row), and `"quit"` ends the loop with
exactly one EXIT.
