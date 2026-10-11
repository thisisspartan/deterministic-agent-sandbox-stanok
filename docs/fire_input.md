# fire_input (TASK-STANOK-CC-243 / FIRE-04)

Keyboard control for the Doom fire: a pure byte→action parser and a
non-blocking raw-mode reader. No dependency on the engine or renderer.

## Contract

`src/fire_input.py`

- `parse_key(data: bytes) -> action | None` — pure table lookup:
  - `b"\x1b[D"` → `"wind_left"`, `b"\x1b[C"` → `"wind_right"`,
    `b"\x1b[A"` → `"intensity_up"`, `b"\x1b[B"` → `"intensity_down"`,
  - `b"q"` and `b"\x03"` (Ctrl-C) → `"quit"`,
  - anything else (empty, unknown bytes, multi-byte noise) → `None`.

- `class KeyReader(fd)`
  - Constructor: if `fd` is a tty, save its termios attributes and enter
    raw mode via `tty.setraw`. On a non-tty fd (pipe, closed fd) the raw
    setup is skipped gracefully — polling still works.
  - `read() -> action | None` — NEVER blocks: `select.select([fd], [], [], 0)`
    gates the read; no data ready → `None` immediately. `EAGAIN`
    (`BlockingIOError`) and other OS errors → `None`. EOF (writer closed) →
    `None`. At most 8 bytes are consumed per read (longer than any known
    sequence); the bytes are handed to `parse_key`.
  - `close()` — restores the saved termios attributes (`TCSADRAIN`);
    idempotent; a no-op when no raw mode was ever set.

## Design notes

- Non-blocking is achieved with `select` timeout 0 rather than `O_NONBLOCK`,
  so the reader does not mutate the fd's file-description flags; `EAGAIN` is
  still handled defensively.
- A partial escape sequence (arrow key split across reads) parses to `None`
  — an unknown sequence is dropped, never misattributed.

## Tests

`tests/fire_input_test.py` (pytest, run via
`scripts/run.sh test tests/fire_input_test.py`) — parser table and noise
cases; `KeyReader` over `os.pipe` (non-blocking proven with a SIGALRM guard,
no sleep trick; parsed actions; drain behavior) and over `pty.openpty()`
(raw mode active while open, termios state restored exactly on close).
