# tetris_cli — module contract (CC-284)

CLI + game loop over `src/tetris_engine` (engine) and `src/tetris_render`
(renderer) — public functions only. Hybrid input (termios-raw TTY keys /
line-based pipe commands), in-place redraw under a TTY, and a bounded
deterministic `--ticks` mode for scripted runs and tests.

Run as `python -m src.tetris_cli`.

## Flags

| flag | type | default | notes |
|---|---|---|---|
| `--seed` | int | 1 | engine RNG seed |
| `--width` | int | 10 | must be >= 1 |
| `--height` | int | 20 | must be even and >= 2 |
| `--fps` | float | 2 | must be > 0 |
| `--ticks` | int | — | N >= 1: bounded deterministic mode |

Unknown flag, invalid value, or odd `--height` -> exit code **2**.
`--help` -> **0**. `main(argv) -> int` parses the flags and delegates
everything to `run_loop()` — the only frame-output path.

## Functions

- `main(argv=None) -> int` — parse flags (argparse), call
  `run_loop(sys.stdin, sys.stdout, ...)`, return its exit code.
- `run_loop(stdin, stdout, *, seed, width, height, fps, ticks=None,
  max_frames=None, sleep=time.sleep, monotonic=time.monotonic) -> int` —
  the game loop and the ONLY path that writes frames. `ticks is not None`
  selects the bounded mode; otherwise the interactive loop.
  `max_frames` bounds the number of emitted frames and `sleep`/`monotonic`
  are injectable clocks — test hooks; production uses the real clock.
  `KeyboardInterrupt` (SIGINT) exits cleanly with 0.

## Input (hybrid)

- `stdin.isatty()` -> termios raw mode (ECHO/ICANON off, restored on
  exit): `a`/Left -> move left, `d`/Right -> move right, `s`/Down -> soft
  drop, `w`/`x`/Up -> rotate, Space -> hard drop, `q` (or Ctrl-C) -> quit,
  rc 0. Keys are polled non-blockingly each tick.
- piped stdin -> line-based command characters: `a` left, `d` right,
  `w` rotate, `s` soft drop, space hard drop, `q` quit. Unknown characters
  are no-ops. Lines are drained non-blockingly (select on the fd; an
  in-memory stream is drained as-is).

## Bounded mode (`--ticks N`)

1. Print the initial frame.
2. Read every line currently available on stdin (never blocks on absent
   input; empty/DEVNULL stdin is valid), apply the commands in order.
   `q` -> return 0 immediately, before any tick.
3. Run exactly N engine ticks, printing one rendered frame after each.
4. Return 0.

No sleeps, no clock reads -> fully deterministic: identical flags + stdin
produce byte-identical stdout. **Never emits `ESC[H`.**

## Interactive mode (no `--ticks`)

Period `1/fps` (monotonic scheduling): poll input, apply commands, engine
tick, render. `q` or SIGINT -> clean exit rc 0.

## In-place redraw (the ESC[H gate)

- Constant `HOME = "\x1b[H"` (CUP). Before every frame **after the
  first**, `run_loop` emits `HOME` — but only when `stdout.isatty()`.
- The first frame is emitted without `HOME` in every mode.
- Pipe stdout (`isatty()` False) contains no `HOME` at all and is
  byte-identical to the TTY stream with the `HOME` sequences removed —
  the home sequence is the only difference between the two streams.

## Frames

Each frame is `tetris_render.render_board(board, active=(overlay, x, y))`
where the overlay matrix carries `piece_id` in its set cells (the renderer
needs no engine knowledge), followed by a newline. `run_loop` starts the
game with `tetris_engine.new_game(seed, width, height)`.

Tests: `tests/tetris_cli_test.py` (`bash scripts/run.sh test
tests/tetris_cli_test.py`).
