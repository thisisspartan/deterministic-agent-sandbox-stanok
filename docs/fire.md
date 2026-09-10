# Doom Fire — terminal 2D fire animation

A terminal port of the classic **Doom fire** effect: a heat map fills the
bottom row with stochastic "fuel" every frame, and each frame the heat
propagates upward — every cell takes the value of a random neighbor one row
below, minus a small random decay. Rendered as blocks, the columns flicker
like rising fire.

## Modules

| Module | Responsibility |
| --- | --- |
| `src/fire_model.js` | Pure heat math. `createFireModel(w, h, { maxHeat, decay, seed, inertia, turbulence })` returns `{ w, h, maxHeat, grid, step }`; `grid[y][x]` is in `[0, maxHeat]` (row `h-1` is the bottom, the heat source). Deterministic per seed (xorshift32). No I/O. |
| `src/fire_render.js` | Pure heat → ANSI mapping. `renderFrame(grid, { maxHeat, palette, density })` returns `h` row strings: `palette: 'ansi256'` (256-color `█` ramp, black→red→orange→white) or `palette: 'symbols'` (` ░▒▓█`, no escapes). |
| `src/main.js` | The terminal front-end: reads the terminal size, runs the fps-paced animation loop (`setInterval`, no busy-loop), handles terminal hygiene and SIGINT, and routes its output straight to the real stdout (fd 1). CommonJS, no dependencies. |

### Realism options (`inertia`, `turbulence`)

Two opt-in realism knobs, both defaulting to `0`; with both `0` the output is
bit-identical to the legacy algorithm (same PRNG call order, same values).
- `inertia` — number in `[0, 1)`, default `0`. Blends each cell's own previous
  value into its new value (`v = inertia*old + (1-inertia)*v`), adding temporal
  smoothing so the flame forms coherent rising tongues instead of grainy noise.
- `turbulence` — number in `[0, 1]`, default `0`. Drives a coarse
  `ceil(h/4) × ceil(w/4)` noise field that drifts slowly in time and is smooth
  in space, nudging heat up/down by row so heat rises in plumes. The field is
  only updated (and consumed from the PRNG stream) when `turbulence > 0`.

Both are validated up front and throw `TypeError` if out of range.

### Renderer option (`density`)

`renderFrame` takes one opt-in boolean `density` (default `false`). With it absent
or `false`, output is bit-identical to the legacy renderer (every hot `ansi256`
cell is a solid `█`, only the color varies). When `density` is `true` and
`palette === 'ansi256'`, brightness is also encoded in the GLYPH DENSITY (in
addition to the color): each hot cell emits `\033[38;5;<n>m` + `SYMBOLS[level]` +
`\033[0m` where `level = min(3, floor(pos/255*4))` (the same mapping `symbols`
mode uses), so cold hot-cells render as dim `░`/`▒` and the core as a bright `█`
— soft, feathered edges around a bright core. `density` is ignored for
`palette: 'symbols'` (which already uses glyph density). If `density` is provided
it must be a boolean, else `renderFrame` throws `TypeError`. `t <= 0` is always a
space.

### App-level realism options (`src/main.js`)

`createApp(opts)` wires the realism options through with realistic defaults, so the
**default** app renders the more realistic fire (coherent rising tongues + soft,
feathered edges). Each option is overridable by the caller:

- `inertia` — default `0.5`, forwarded to the heat model as `modelOpts.inertia`.
- `turbulence` — default `0.5`, forwarded to the heat model as `modelOpts.turbulence`.
- `density` — default `true`, forwarded to the renderer as
  `renderFrame(model.grid, { ..., density })`. It only affects `ansi256` (TTY)
  mode; in headless `symbols` mode the renderer ignores it (which is fine and expected).

The three values are also exposed on the object returned by `createApp` (alongside
`w, h, fps, maxHeat, start, stop`), so the defaults/overrides are observable:
`{ w, h, fps, maxHeat, inertia, turbulence, density, start, stop }`.

## Run

```sh
node src/main.js
```

`Ctrl+C` (SIGINT) stops the app cleanly (exit code 0).

## Test

```sh
bash scripts/run.sh test tests/fire_model.test.js tests/fire_render.test.js tests/fire_app.test.js
```

## Terminal hygiene (TTY mode only)

- **Alternate screen buffer**: `\033[?1049h` on start, `\033[?1049l` on stop — the animation lives in the alt screen and leaving it restores your shell screen.
- **Cursor**: hidden (`\033[?25l`) before the first frame, shown again (`\033[?25h`) on stop.
- **Color reset**: `\033[0m` on stop so the shell keeps a clean color state.
- Frames are positioned at the top of the screen with a `\033[H` home prefix each tick.
- **SIGINT**: the script entry point registers `process.on('SIGINT')`, which calls `stop()` and exits with code 0. `stop()` is idempotent.
- Requiring `src/main.js` as a module has **no side effects**: no loop starts, nothing is written, no escapes are emitted. It does install one thin synchronous passthrough on `process.stdout.write` so that all subsequent stdout traffic (frames included) reaches the real terminal (fd 1) even when that function has been wrapped by test instrumentation — the module itself stays silent.

## Headless fallback

When `process.stdout` is not a TTY (sandbox, piped output):

- `getTerminalSize()` never throws — it uses `process.stdout.columns/rows` when they are positive integers, otherwise the **80 × 24** fallback.
- **No terminal escapes** are emitted (no alt screen, cursor, or home positioning); frames are still produced at `fps` via the injectable `write(string)` function (default `process.stdout.write`), rendered with the escape-free `symbols` palette.
- This holds even under the new realistic defaults (`inertia=0.5`, `turbulence=0.5`, `density=true`): headless mode still uses the escape-free `symbols` palette, and the renderer ignores `density` in `symbols` mode, so frames never contain terminal escapes.
