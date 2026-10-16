# fire — a console fire (`src/fire.py`)

One module, four concerns. Python 3.11, stdlib only.

## 1. Simulation (pure)
`new_field(width, height)` -> `height` rows x `width` floats in [0,1]; row 0 is the top, the last row the base. `advance(field, rng)` returns a NEW field (the input is never mutated): the base row is ignited with seeded values near 1.0; every cell above takes a seeded choice among the cells below it (same column, left, right — only cells that exist), reduced by seeded cooling jitter and clamped to [0,1]. That choice is what makes tongues; a fixed neighbour rule would give a static cone. `simulate(seed, width, height, ticks)` yields the fields after ticks 1..ticks (frame 0 = tick 1).

## 2. Palette (pure)
`heat_to_rgb(heat, base_zone=False, rng=None)` -> `(r,g,b)`, or `None` when heat <= 0 (an empty cell). Linear interpolation between the stops white-hot -> yellow -> orange -> red-orange -> red -> dark red; luminance increases with heat. `base_zone=True` selects the blue combustion gradient (blue-dominant, b > r) used by the bottom `BASE_ZONE_ROWS` rows. A seeded `rng` adds a small per-cell jitter that breaks colour banding; without it the mapping is exact.

## 3. Renderer (pure)
`render_frame(field, base_zone_rows=BASE_ZONE_ROWS, rng=None)` -> ONE frame string: half-block `▀` characters, two grid rows per character row (foreground = upper cell, background = lower cell), lines joined by `\n`, 24-bit truecolor `\x1b[38;2;R;G;Bm`. Zero-heat cells render as plain spaces with no ANSI at all.

## 4. CLI (IO only, headless-safe)
The animation loop runs ONLY under `if __name__ == "__main__":`. With a real TTY: ~30 FPS, clear screen per frame, centred in `shutil.get_terminal_size()` (fallback 80x24); SIGINT stops, restores the cursor (`\x1b[?25h`), resets ANSI (`\x1b[0m`), exit 0. WITHOUT a TTY (stdin is not a terminal — how `run.sh smoke` invokes it) it renders exactly ONE frame to stdout and exits 0, never an infinite loop. Flags: `--seed --width --height --fps --frames N --frame N`; the last two make the animation deterministically testable headlessly. The flame is clamped to the terminal size, so a tiny terminal renders rather than failing.

## Seeded determinism
All randomness comes from a `random.Random` seeded by the single `--seed` value. The colour-jitter stream is *derived* from that seed rather than shared with the simulation stream, so rendering a frame never perturbs the heat field: same seed + same dimensions => identical frames, whatever was rendered before them.

## Run the demo
`python3 src/fire.py` — Ctrl-C to stop. Tests: `bash scripts/run.sh test tests/fire_test.py`. Smoke: `bash scripts/run.sh smoke src/fire.py`.
