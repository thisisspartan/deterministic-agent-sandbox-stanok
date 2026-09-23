# fire — deterministic multicolor terminal fire

`src/fire.py` (stdlib only, no side effects on import). Four separated
concerns:

1. **Simulation** — `FireSim(width, height, seed=42, inject=True)`: a
   deterministic 2D heat-field grid. Per `tick()`: turbulence-offset
   upward diffusion with per-cell cold pockets (the flame licks, it is
   not a solid cone), cone taper, decay, base-row injection in the
   central third (ragged, never touching the terminal edges), and a
   sparse smoke-particle list. One seeded `random.Random` drives every
   draw, so a fixed seed reproduces every frame byte-for-byte.
2. **Palette** — pure `palette(heat, is_base, blank=0.01) -> (r, g, b) |
   None`: hot→cold gradient (white-hot → yellow → orange → red → dark
   red), blue combustion gradient for base-zone cells, `None` below the
   blank threshold (`BLANK_THRESHOLD = 0.10`). `jittered_rgb(rgb, x, y)`
   adds bounded per-cell jitter (±8 per channel) to break banding.
3. **Renderer** — pure `render(sim, color_mode="truecolor") -> str`:
   `height` newline-joined rows of exactly `width` half-block
   (`▀`) cells or spaces.
4. **Loop** — IO only: ~30 FPS TTY animation (centered), a single
   headless frame when stdout is not a TTY, deterministic `--frame N` /
   `--frames N` modes, clean SIGINT shutdown.

## Color modes

`render(sim, color_mode=...)` picks the escape style:

| mode | cell encoding | notes |
|------|---------------|-------|
| `"truecolor"` (default) | `\x1b[38;2;R;G;Bm\x1b[0m▀` | 24-bit; byte-identical to the original output |
| `"256"` | `\x1b[38;5;Nm\x1b[0m▀` | `N = rgb_to_256(jittered rgb)`, N in 0..255 |
| `"16"` | `\x1b[38;5;Nm\x1b[0m▀` | `N = rgb_to_16(jittered rgb)`, N in 0..15 |
| `"none"` | `▀` | no ANSI escapes |

`rgb_to_16(rgb) -> int` (CC-116): nearest of the 16 basic ANSI colors
(standard 0..15 palette — black, red, green, yellow, blue, magenta,
cyan, white, then bright variants 9..15), deterministic, ties resolve
to the lower index.

**`"16"` is the last-resort fallback** for terminals that drop BOTH
24-bit truecolor (`\x1b[38;2;...`) and 256-color (`\x1b[38;5;N`, N>15)
escapes — it renders only the 16 basic ANSI colors understood by every
terminal. Auto-detection cannot know that a terminal lies about its
capabilities, so on such terminals the user picks the mode explicitly:
`--color 16`.

`rgb_to_256(rgb)` (CC-113): nearest of the standard 256-color palette
(16 base colors, 6x6x6 cube, 24-step gray ramp); exact distance ties
resolve to the cube color, so black → 16, white → 231.

## CLI

```
python3 src/fire.py [--seed N] [--width W] [--height H] [--fps FPS]
                    [--frame N | --frames N]
                    [--color {truecolor,256,16,none}]
```

`--color` forces the color mode; without it, `detect_color_mode`
auto-detects on a TTY (`"none"` for `NO_COLOR`/`TERM=dumb`; `"truecolor"`
for `COLORTERM` truecolor/24bit; `"256"` otherwise) and falls back to
`"truecolor"` headless.

## Tests

`bash scripts/run.sh test tests/<file>` (pytest via the stack registry):
`fire_basic_test.py`, `fire_realism_test.py`, `fire_polish_test.py`,
`fire_shape_test.py`, `fire_color_test.py` (256-color + detection),
`fire_width_test.py`, `fire_color16_test.py` (16-color fallback, CC-116).
Smoke: `bash scripts/run.sh smoke src/fire.py`.

Preview headlessly (never run the animation unbounded):
`timeout 3 python3 src/fire.py < /dev/null | head -c 3000`.
