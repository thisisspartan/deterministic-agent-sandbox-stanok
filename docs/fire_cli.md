# fire_cli — module contract (CC-289)

CLI animation over `src/fire_engine` (`FireEngine(seed, width, height)`,
`step()`, `grid`) and `src/fire_render` (`render(grid)`) — public APIs
only. In-place flame under a TTY, a bounded deterministic `--frames` mode
for scripted runs, non-blocking input polling.

Run as `python -m src.fire_cli`.

## Flags

| flag | type | default | notes |
|---|---|---|---|
| `--seed` | int | 1 | engine RNG seed |
| `--width` | int | 40 | must be >= 2 |
| `--height` | int | 12 | must be >= 2 |
| `--fps` | float | 15.0 | must be > 0 |
| `--frames` | int | — | N >= 1: bounded mode, exactly N frames |

Unknown flag or invalid value -> exit code **2**. `--help` -> **0**. No
other flags. `main(argv) -> int` parses the flags and delegates
everything to `run_loop()` — the only frame-output path.

## Functions

- `main(argv=None) -> int` — parse flags (argparse), call
  `run_loop(sys.stdin, sys.stdout, ...)`, return its exit code.
- `run_loop(stdin, stdout, *, seed, width, height, fps, frames=None,
  sleep=time.sleep, monotonic=time.monotonic) -> int` — the loop and the
  ONLY path that writes frames. `frames is not None` selects the bounded
  mode; `None` the interactive loop. `sleep`/`monotonic` are injectable
  clocks — test hooks; production uses the real clock. SIGINT (and a
  raced `KeyboardInterrupt`) exits cleanly with 0.

## The TTY segment (stdout.isatty() — BOTH modes)

When `stdout.isatty()`, in bounded and interactive mode alike:

1. At start: hide the cursor (`\x1b[?25l`), save the termios attributes
   of a TTY stdin and enter cbreak (`tty.setcbreak`; ISIG preserved).
2. Before EVERY frame, including the first: emit CUP `\x1b[H` — the
   first frame is homed too (the tail-residue lesson: a terminal that
   does not start at (0,0) keeps an unhomed first frame).
3. At ANY exit (success, q, SIGINT, error): restore termios (finally)
   and show the cursor (`\x1b[?25h`).

Outside a TTY: no `\x1b[H`, no `\x1b[?25l`, no `\x1b[?25h`; termios is
never touched. A stdin that is not a real TTY (no fileno) skips only the
cbreak part; the cursor sequences still bracket the run.

## Frames

Each tick: `engine.step()`, `render(engine.grid())`, write to stdout,
flush; the frame is followed by a newline (render joins its lines with
`\r\n` and adds no trailing break). Inter-frame pause = `1/fps`
(monotonic deadline), taken in 0.05 s steps with an input poll between
them — a typed `q` is seen in well under 0.5 s. stdout carries only
frames and the segment sequences; stderr is unused.

## Input

- TTY stdin (cbreak): non-blocking key reads (`select` + `os.read`) in
  small steps between frames; `q` -> quit rc 0, other keys are no-ops.
- piped stdin: lines available right now are drained (`select` on the
  fd; an in-memory stream is drained as-is); a line containing `q` ->
  quit rc 0. EOF (e.g. stdin=DEVNULL) is not an error and does not end
  the loop.
- SIGINT: a signal handler sets a quit flag -> clean exit rc 0 with the
  full TTY-segment cleanup (termios/cursor restored) when in a TTY.

## Bounded mode (`--frames N`)

Emit exactly N frames (each after one `engine.step()`) and return 0.
Input is optional (empty pipe or DEVNULL is valid); a `q` in a pipe
quits immediately, before N is exhausted. In a non-TTY it adds no
`\x1b[H`. Deterministic: identical argv (same `--seed`) + identical
input -> byte-identical stdout.

## Interactive mode (no `--frames`)

Loop until `q` or SIGINT; both exit rc 0.

Tests: `tests/fire_cli_test.py` (`bash scripts/run.sh test
tests/fire_cli_test.py`); the live-terminal invariants are the protected
acceptance contract `tests/fire_terminal_test.py`.
