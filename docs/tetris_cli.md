# tetris_cli — contract (CC-292)

Terminal boundary layer of the TETRIS3 wave: the consumer of `tetris_engine`
(rules) and `tetris_render` (frames), and the only module in the wave that
does I/O. Two modes: a bounded pipe tool (`--ticks N`) and an interactive
terminal loop. Tests: `tests/tetris_cli_test.py`; the boundary accept under a
real PTY is the host-authored `tests/tetris_terminal_test.py`.

## Entry points (pinned)

- `main(argv) -> int`; launched as `python -m src.tetris_cli` from the repo
  root. Engine/renderer imports work at both entry points: package-relative
  (`python -m src.tetris_cli`) with a bare-import fallback
  (`PYTHONPATH=src`, `import tetris_cli`).
- `run_loop(stdin, stdout, *, seed=1, width=10, height=20, fps=2.0,
  ticks=None, sleep=time.sleep, monotonic=time.monotonic) -> int` — the
  single frame-output point. `sleep`/`monotonic` are keyword hooks so tests
  run without wall-clock. All TTY gates call `isatty()` on the passed
  `stdin`/`stdout` objects.

## Flags

`--seed` int (default 1), `--width` int (10), `--height` int (20), `--fps`
float (2.0), `--ticks` int (optional). Invalid input — `--height` odd or
`< 2`, `--width < 2`, `--fps ≤ 0`, `--ticks < 1`, a non-numeric value, a
missing value, an unknown flag, or a positional argument — → rc 2, usage on
stderr, stdout empty (no frame bytes). `--help`/`-h` → rc 0.

## Frame

A frame is the string returned by `render_board(board, active)` printed
unchanged plus `"\n"` after each frame. `active` is the active piece
overlaid in its own color: `(piece_id-colored shape, x, y)`; `None` when
there is no active piece.

## Keys (pinned)

`a` / arrow-left (`ESC [ D`) → `try_move(-1)`; `d` / arrow-right →
`try_move(1)`; `w` / arrow-up → `try_rotate(1)`; `s` / arrow-down →
`soft_drop`; space → `hard_drop`; `q` and byte `\x03` → quit (rc 0). An
invalid move leaves the state unchanged; all other characters (including
`\n`) are ignored.

## Bounded mode (`--ticks N`) — the pipe tool

- Read stdin first: a pipe/DEVNULL is read to EOF (a finite input — this is
  what makes the bounded stream deterministic); a TTY is polled
  non-blocking. Empty stdin/DEVNULL is legal. Commands are applied in order.
- `q`/`\x03` in the input → rc 0 immediately: no ticks run, no frames
  (frames in this mode are produced by ticks only).
- Otherwise exactly N gravity ticks, exactly one frame after each; if
  `is_game_over` occurs among the ticks → print the final frame, rc 0,
  stop.
- Never emits `ESC[H`, `ESC[2J`, `ESC[?25` — even when stdout is a TTY.
- Determinism: identical argv + stdin → byte-identical stdout (no time is
  used in this mode).

## Interactive mode (no `--ticks`)

- TTY stdin → termios raw: `ICANON`/`ECHO` cleared from `lflag` only
  (`OPOST` untouched — newline translation must stay on); the attributes are
  deep-copied (including the `cc` list) and the originals are restored with
  `TCSADRAIN` in `finally`.
- Period `1/fps` via `monotonic`/`sleep`. Each period: poll the available
  commands non-blocking, apply them, then one gravity tick and one frame.
- `stdout.isatty()`: every frame, **including the first**, is prefixed with
  the exact bytes `"\x1b[H"`. Non-TTY stdout: no `ESC[H` (the stream is
  byte-identical to the same scenario without homes).
- The cursor is never hidden: no `ESC[?25l` in the output.
- `q`, `\x03`, `SIGINT` (trapped; also `KeyboardInterrupt`), or a closed
  non-TTY stdin (EOF on a real fd) → rc 0 with termios restored.
  `is_game_over` → print the final frame (homed if TTY), rc 0.

## Exit codes

0 — quit (`q`/`\x03`/SIGINT/EOF stdin), game over, `--help`. 2 — invalid
flags or values.
