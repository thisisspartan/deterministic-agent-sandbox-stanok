# fire — deterministic multicolor terminal fire (`src/fire.py`)

Stdlib-only, single module. No side effects on import. Four separated
concerns:

- **Simulation** — `FireSim(width, height, seed=42, inject=True)`:
  deterministic 2D heat field in [0, 1] (`heat[y][x]`, `y = 0` at the top).
  Per `tick()`: turbulence-offset upward diffusion with per-cell cold
  pockets (internal gaps — the flame licks, it is not a solid cone),
  decay, base-row injection only in the central third of the width
  (edge ignitions below `BLANK_THRESHOLD = 0.10` are dropped, so the
  flame never touches the terminal edges), and a sparse smoke-particle
  list rising above the flame top. One seeded `random.Random` drives
  every draw; a fixed seed reproduces every frame byte-for-byte.
- **Palette** — `palette(heat, is_base, blank=0.01) -> (r, g, b) | None`:
  multi-stop hot→cold gradient (white-hot → yellow → orange → red),
  blue combustion gradient for base-zone cells, `None` below the
  blank threshold. `jittered_rgb(rgb, x, y)` adds bounded per-cell
  jitter (±8/channel) that breaks banding.
- **Renderer** — `render(sim, color_mode="truecolor") -> str`:
  one ANSI frame of half-block (`▀`) cells, `height` rows of exactly
  `width` cells; zero heat renders as plain spaces; smoke as faint
  gray.
- **Loop** — under `if __name__ == "__main__"`: ~30 FPS animation on a
  TTY (centered), one headless frame when stdout is not a TTY,
  deterministic `--frame N` / `--frames N` CLI modes, clean SIGINT
  shutdown.

## Color modes

`color_mode` selects the escape style:

- `"truecolor"` — 24-bit `\x1b[38;2;R;G;Bm\x1b[0m▀` (the `render`
  default, byte-identical to the original output);
- `"256"` — `\x1b[38;5;Nm\x1b[0m▀` with `N = rgb_to_256(jittered rgb)`;
- `"none"` — plain `▀`, no ANSI escapes.

`rgb_to_256(rgb)` quantizes to the nearest color of the standard
256-color palette (16 base colors, 6x6x6 cube, 24-step gray ramp);
exact distance ties let the cube color win, so black → 16 and
white → 231.

## Color auto-detection (CC-115)

`detect_color_mode(env=None)` (module-level, `env` defaults to
`os.environ`) returns:

- `"none"` — EXPLICIT opt-out only: `NO_COLOR` set to a non-empty
  value (wins over everything), or `TERM == "dumb"`;
- `"truecolor"` — `COLORTERM` contains `truecolor` or `24bit`
  (case-insensitive);
- `"256"` — otherwise (the default: most terminals support 256
  colors even without `COLORTERM`, so a no-signal environment must
  NOT render monochrome).

CLI: on a TTY the mode is `detect_color_mode(os.environ)`; headless
(non-TTY) stays `"truecolor"` (contract unchanged); `--color
{truecolor,256,none}` always forces the mode.

## Tests

- `tests/fire_color_test.py` — rgb_to_256, detect_color_mode
  (256 default, NO_COLOR/TERM=dumb opt-out, truecolor precedence),
  256-mode cell alignment, default-render truecolor regression guard,
  base-row internal gaps, no edge contact.
- `tests/fire_basic_test.py`, `tests/fire_realism_test.py`,
  `tests/fire_polish_test.py`, `tests/fire_shape_test.py`,
  `tests/fire_width_test.py` — determinism, palette, shape, realism
  and width contracts (CC-108…CC-114).

Run: `bash scripts/run.sh test tests/fire_color_test.py`
(all six fire test files pass together).
