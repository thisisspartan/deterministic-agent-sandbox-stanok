# doomfire — component contract

The classic DOOM fire effect for the terminal. Later tickets append their
sections (palette, terminal controller, CLI); this page documents the core
simulation module only.

## src/doomfire_core.py — core model (pure math, no I/O)

### Field representation

A heat field is `list[list[int]]`: rows top→bottom, `field[-1]` is the
bottom (source) row, every cell an `int` in `[0, 255]`. Heat never leaves
that range. Degenerate sizes are valid: `W=1` (offsets clamp to 0), `H=1`
(a step only reseeds the bottom row).

### API

- `create_field(width: int, height: int) -> list[list[int]]`
  All-zero field. Raises `ValueError` if `width < 1` or `height < 1`.
- `seed_bottom(field, rng) -> None`
  Mutates the bottom row in place: for x left→right,
  `field[-1][x] = rng.randint(128, 255)`.
- `step(field, rng) -> list[list[int]]`
  ONE frame advance, double-buffered: returns a NEW field, never mutates
  the input. For each row `y` in `0..height-2` top→bottom, for each `x`
  left→right:
  `off = rng.choice([-1, 0, 1])`, `decay = rng.randint(1, 3)`,
  `src_x = clamp(x + off, 0, width-1)`,
  `new[y][x] = max(0, field[y+1][src_x] - decay)`.
  After all rows: `seed_bottom(new, rng)`.
- `simulate(width, height, steps, seed) -> list[list[int]]`
  Convenience driver: `rng = random.Random(seed)`, `create_field`,
  `seed_bottom`, then `steps × step`; returns the final field.
  `steps >= 0` (0 → the seeded field).

### RNG-order contract

All randomness flows through the passed `rng` object; no module-level RNG
state. The call order is part of the contract and makes a run
reproducible for a given `rng`: rows top→bottom, columns left→right,
`off` before `decay`, bottom-row reseeding last.

### Invariants

- Every cell stays in `[0, 255]`; after any `step`, the bottom row is all
  in `[128, 255]`.
- Decay: for `y < height-1`, `max(new[y]) <= max(old[y+1])` — a row can
  only inherit heat from the row below it, minus decay.
- Purity: the module imports only `random`; no `sys`/`os`/`time`, no
  file/socket/print anywhere.

## doomfire_palette

### src/doomfire_palette.py — palette and frame formatter (pure formatting, no I/O)

Maps a heat field (the `list[list[int]]` shape of the core model) to a
renderable string. The module imports nothing from the project and no I/O
stdlib (`sys`/`os`/`time`); it only returns strings.

### API

- `FIRE_PALETTE` — module constant: exactly 21 `(r, g, b)` tuples, the
  classic DOOM fire colormap, black→red→orange→yellow→white, monotone
  non-decreasing per channel; first `(0,0,0)`, last `(255,255,255)`.
- `heat_to_rgb(heat: int) -> tuple[int, int, int]`
  `heat` clamped to `[0, 255]`, then `FIRE_PALETTE[heat * 20 // 255]`
  (`0 → palette[0]`, `255 → palette[20]`).
- `render_frame(field, ascii: bool = False) -> str`
  The WHOLE frame as one string, no I/O. Every output line ends `"\n"`.
  - Half-block mode (default): each output line renders a PAIR of field
    rows `(0,1), (2,3), ...`; an odd last row pairs with cold (heat 0).
    Output line count = `(height + 1) // 2`. One cell:

    ```
    "\x1b[38;2;{r1};{g1};{b1}m"  # foreground = TOP row heat color
    "\x1b[48;2;{r2};{g2};{b2}m"  # background = BOTTOM row heat color
    "▀"                          # U+2580 upper half block
    "\x1b[0m"                    # reset
    ```
  - `ascii=True`: one char per cell, rows rendered 1:1 (no pairing, no
    U+2580, no escapes). Charset `" .:-=+*#%@"`, char index
    `= heat * 9 // 255` (heat clamped). Line count == height.

### Frame format invariants

- `render_frame` never writes to a stream; it returns the complete string.
- Half-block output: `(height + 1) // 2` lines; ASCII output: `height`
  lines; both always newline-terminated.
- Degenerate sizes are valid: a 1×1 field renders one line (its single
  cell pairs with black in half-block mode).
- Purity: no project imports, no `sys`/`os`/`time`, no `print`.

## doomfire_terminal

### src/doomfire_terminal.py — terminal controller (lifecycle only, no main loop)

Owns the terminal lifecycle: alternate screen, cursor visibility, teardown and
signal flags. It does NOT import the core or the palette, does NOT read the
real terminal size, and contains no main loop (the CLI comes in a later
ticket). The module imports only `signal` and `atexit` — no `sys`/`os`/`time`,
no project modules; it never touches `sys.stdout` itself.

### API

- `TerminalController(stream)`
  `stream` is any object with `write(str)` and `flush()` (dependency
  injection — tests pass `io.StringIO`).
- `setup()` — writes exactly `"\x1b[?1049h\x1b[?25l"` (enter alternate
  screen + hide cursor), registers `teardown` via `atexit.register` exactly
  once, and installs handlers for SIGINT, SIGTERM and SIGWINCH via
  `signal.signal`. Idempotent: a second `setup()` writes and registers
  nothing.
- `present(frame: str)` — `stream.write(frame)` then `stream.flush()`:
  exactly one write and one flush per whole frame, never per-cell writes.
- `teardown()` — writes exactly `"\x1b[?25h\x1b[?1049l"` (show cursor +
  leave alternate screen) and flushes. Idempotent: guarded by a flag, the
  second call is a no-op and must not raise — safe from `atexit` after an
  explicit call or after an exception.
- `clear_flags()` — resets `should_exit`/`resize_requested` to `False`
  (called by the CLI at frame boundaries).
- Module constants `EXIT_SIGINT = 130`, `EXIT_SIGTERM = 143`.

### Signal-handler contract

Handlers follow the async-signal-safe pattern: they ONLY set flags —
SIGINT/SIGTERM set `self.should_exit` and record `self.exit_code`
(`130`/`143`); SIGWINCH sets `self.resize_requested`. No I/O, no logic in
handler context; the main loop (CLI ticket) polls the flags and calls
`clear_flags()` at frame boundaries.

### Teardown guarantees

- Exactly one teardown sequence per controller, whichever path reaches it
  (explicit call, `atexit`, or both — the guard makes the second a no-op).
- The full lifecycle output on a stream is exactly
  `"\x1b[?1049h\x1b[?25l"` + frames + `"\x1b[?25h\x1b[?1049l"`.

## doomfire (CLI)

### src/doomfire.py — runner CLI (wires the model, the palette and the controller)

The only component that touches I/O. It imports `sys`, `argparse`, `random`,
`shutil`, `time` and the three project modules — nothing else (no
`curses`/`termios`, no `os`/`signal`/`atexit`: the terminal lifecycle stays
with `TerminalController`). Importing the module has no side effects: no loop
starts, nothing is printed.

### Entry point

- `main(argv=None) -> int` — testable entry; `if __name__ == "__main__":
  sys.exit(main())`. `argv=None` falls back to `sys.argv[1:]`.

### Flags

| Flag | Type | Default | Contract |
| --- | --- | --- | --- |
| `--headless N` | int ≥ 0 | absent | run N frames non-interactively and exit 0 |
| `--seed S` | int | `0` | seed of the private `random.Random` |
| `--width W` | int ≥ 1 | `80` | field width in cells |
| `--height H` | int ≥ 1 | `24` | field height in rows |
| `--fps F` | int 1..60 | `30` | interactive frame cap |
| `--ascii` | flag | off | ASCII ramp instead of ANSI half-blocks |

Out-of-range or non-integer values are argparse usage errors (`SystemExit`
code 2), before any frame is produced.

### Headless mode (`--headless N`)

No TTY required, no signals, no sleep, no alternate-screen sequences. The
field is built with `create_field` + `seed_bottom` and advanced with repeated
`step`, all randomness flowing through a private `random.Random(seed)`; for
each of the N frames the CLI renders `render_frame(field, ascii=args.ascii)`
and writes `frame.encode("utf-8")` to `sys.stdout.buffer` (explicit UTF-8, so
the bytes are identical under any locale), then flushes once. Exit code 0.

- Deterministic: identical arguments → byte-identical stdout. No global RNG
  state is used, so two calls in one process give the same bytes.
- Frame count: exactly N frames; `N == 0` writes nothing and exits 0. Each
  frame is `(height + 1) // 2` lines in half-block mode, `height` lines in
  ASCII mode, always newline-terminated.

### Interactive mode (no `--headless`)

Only when `sys.stdout.isatty()`. Without a TTY the CLI prints a one-line hint
naming `--headless` to stderr, writes nothing to stdout, and returns 2 — no
alternate screen, no handlers, no frame.

Loop (after `controller.setup()`):

1. `resize_requested` → re-read `shutil.get_terminal_size()`, clamp to
   ≥ 1×1, rebuild the field keeping the heat of the overlapping region
   (top-left aligned; a bottom row left without heat is reseeded).
2. `should_exit` → return the controller's recorded exit code
   (`130`/`143`).
3. `clear_flags()` — flags are cleared after both are handled and before the
   frame is produced, so a signal arriving during `present`/`sleep` is caught
   at the top of the next iteration instead of being swallowed.
4. `step` the model, `controller.present(render_frame(...))`.
5. Pace: `time.sleep(max(0, next_deadline - time.monotonic()))` with
   `next_deadline += 1/fps` — monotonic, no busy-wait.

Teardown is the controller's (atexit + signal flags); the CLI never writes
`"\x1b[?1049h"`, `"\x1b[?1049l"`, `"\x1b[?25l"` or `"\x1b[?25h"` itself.
