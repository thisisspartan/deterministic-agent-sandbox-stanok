# fire_cli — CLI + animation loop (`src/fire_cli.py`)

Stage 3 of 3 of the console-fire program: the **only module with IO** —
argparse, writes to stdout, terminal size probing, sleeps. It composes
`fire_sim` (seeded fields + palette) and `fire_render` (field -> frame string)
into a runnable program; it adds no numerics and no glyphs of its own. Python
3.11, stdlib only. The contract is pinned by `tests/fire_cli_test.py`.

## Flags

| Flag | Default | Valid range | Meaning |
|---|---|---|---|
| `--seed INT` | `1` | any int | seeds the simulation and the color stream |
| `--width INT` | `40` | `>= 1` | simulation grid width |
| `--height INT` | `16` | `>= 1` **and EVEN** | simulation grid height (the renderer pairs two field rows per character line) |
| `--fps INT` | `30` | `>= 1` | animation rate, one frame per `1/fps` seconds |
| `--frames N` | — | `N >= 1`, **exclusive with `--frame`** | print N frames to stdout and exit |
| `--frame N` | — | `N >= 0`, **exclusive with `--frames`** | print only frame N of the same sequence and exit |

Neither of the last two: animate (see *Animation*).

## Exit codes

| rc | When |
|---|---|
| `0` | frames printed, or the animation ended on SIGINT |
| `2` | usage error: `parser.error(...)` prints the usage + the offending flag to **stderr**, no traceback, nothing on stdout (bad range, odd `--height`, negative frame count, `--frames` with `--frame`) |

## Frame stream (`--frames`, `--frame`)

Each frame is a block of `height // 2` lines; blocks are separated by a blank
line (`"\n\n"` — the **frame separator**); stdout ends with a newline. So
`--frames N` output splits on the frame separator into exactly N blocks of
equal line count.

**Prefix property.** `--frame N` output is byte-identical to the last block of
`--frames N+1` (same seed/width/height), and to block N of any longer run.
It holds because the earlier frames are still simulated *and rendered* —
advancing the color stream — and only the last block is printed.

## Seeded determinism

One `random.Random(seed)` drives `heat_to_rgb` across every rendered frame
(`render_frame`'s `color_rng`); `fire_sim.simulate` keeps its own rng seeded
with the same value, so rendering never perturbs the heat field. Same seed +
same dimensions => byte-identical output, whatever was rendered before.

## Canvas

`shutil.get_terminal_size((FALLBACK_COLUMNS, FALLBACK_ROWS))` (from
`fire_render`) feeds `compose_frame`. The canvas is clamped **up** to the
frame's own size: `compose_frame` measures raw string length, and a truecolor
frame is several times wider in characters than in glyphs — a small terminal
renders the whole flame instead of raising. The grid is always `--width` x
`--height`. In the deterministic modes the canvas is exactly as tall as the
frame (padding each block to the terminal height would bury the frame
separator between blank lines).

## Animation (no `--frames`/`--frame`)

Loops frames at `1/fps` (`time.sleep`), clearing and homing the cursor
(`"\x1b[2J\x1b[H"`) to redraw the full-screen canvas in place, until SIGINT
(`KeyboardInterrupt`) -> returns `0`, no traceback. It runs until interrupted,
so `scripts/run.sh smoke src/fire_cli.py` hits the 10 s smoke timeout (rc=124)
by design: the deterministic modes are the testable surface.

## Usage

`python3 src/fire_cli.py --seed 7 --width 60 --height 22` — Ctrl-C to stop.
Deterministic: `python3 src/fire_cli.py --frames 3 --seed 7 | cat`.

Tests: `bash scripts/run.sh test tests/fire_cli_test.py` — or the whole suite:
`bash scripts/run.sh test --all`.
