# tetris_cli — module contract (CC-279)

CLI + game loop over `src/tetris_engine` (pure state) and `src/tetris_render`
(pure frames). This module owns **all I/O** — argument parsing, hybrid input,
frame output, tick pacing — and adds no game logic of its own: every state
change goes through the engine's public functions, every frame through
`render_board`. Tests: `tests/tetris_cli_test.py`.

Importable both ways: as a package module (`python -m src.tetris_cli`) and as a
flat module (`src/` on `sys.path`, the pytest runner's form).

## Entry point

- `main(argv=None) -> int` — returns the exit code, never raises `SystemExit`.
  `rc 0` — the game ran (or `--help`); `rc 2` — unknown flag, invalid value,
  odd `--height`. `KeyboardInterrupt` / a closed stdout → `rc 0`.
- `python -m src.tetris_cli` → `sys.exit(main())`.

## Flags

| Flag | Type | Default | Valid |
|---|---|---|---|
| `--seed` | int | `1` | any int |
| `--width` | int | `10` | `>= 1` |
| `--height` | int | `20` | `>= 2` and **even** (the renderer pairs board rows) |
| `--fps` | float | `2.0` | finite and `> 0` |
| `--ticks N` | int | absent | `N >= 1`; selects the bounded mode |

Unknown flag, unparseable value, out-of-range value or an odd `--height` →
`rc 2` (a one-line message on stderr). `--help` → `rc 0`.

## Input (hybrid, chosen by `stdin.isatty()`)

- **TTY** → the terminal is put into raw mode via `termios` (attributes are
  restored on exit). Keys: `a`/`←` left, `d`/`→` right, `s`/`↓` soft drop,
  `w`/`x`/`↑` rotate (clockwise), `Space` hard drop, `q` or `Ctrl-C` quit.
  Keys are polled with `select` inside the frame period; a partial escape
  sequence is ignored.
- **Pipe / redirect** → command characters, line by line (a line may hold
  several): `a` left, `d` right, `w` rotate, `s` soft drop, ` ` (space) hard
  drop, `q` quit. Unknown characters are ignored.
- An unusable stdin (closed, no `fileno()` — e.g. a captured pytest stdin) is
  treated as end of input, never as an error.

Reading never blocks on the absence of input: `select(..., 0.0)` + `os.read`.
The bounded mode allows a `0.05 s` grace for the **first** byte only, so a pipe
whose writer starts a moment later is not mistaken for "no input".

## Bounded mode — `--ticks N` (deterministic)

1. Read every line currently available on stdin (empty/`DEVNULL` stdin is fine).
2. Apply the commands in order. `q` → print the current frame and return `rc 0`
   **immediately**: the remaining commands and all ticks are skipped.
3. Otherwise run exactly `N` `engine.tick` steps, paced at `1/fps`, printing one
   frame per tick — the last frame printed is the final frame. `rc 0`.

Output depends only on `seed/width/height/commands/ticks` (the engine is seeded
and the renderer is pure), so two identical runs produce identical stdout.

## Interactive mode (no `--ticks`)

Print the initial frame, then loop with period `1/fps`: read input
non-blockingly, apply it, sleep to the deadline, `engine.tick`, redraw.
`q`, `Ctrl-C`, `SIGINT` (handler → clean exit) or **end of piped input** (EOF —
nothing more can ever be typed) ends the run with `rc 0`. Terminal attributes
and the signal handler are restored on exit.

## Frames

Each frame is `render.render_board(board, active=(piece_matrix, x, y))` plus a
newline; in a game-over state the active overlay is omitted. Written to
`sys.stdout`; if the text stream cannot encode `▀`, the UTF-8 bytes are written
to `sys.stdout.buffer` instead.

## Constants

`DEFAULT_SEED = 1`, `DEFAULT_FPS = 2.0`, `PIPE_COMMANDS`, `KEY_COMMANDS`,
`ARROW_COMMANDS` (`ESC [ A/B/C/D` → rotate / soft / right / left),
`INPUT_GRACE = 0.05`, `EXIT_OK = 0`, `EXIT_USAGE = 2`.
