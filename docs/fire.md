# fire

`src/fire.py` — a deterministic multicolor terminal fire (CC-108..CC-113).
Stdlib only, single module, no side effects on import. Four concerns:
`FireSim` (deterministic 2D heat field), `palette` (heat → RGB),
`render` (ANSI half-block frames), and the CLI loop (TTY animation or a
single headless frame). A fixed seed reproduces every frame byte-for-byte.

## Color modes (CC-113)

The renderer picks its escape style via `render(sim, color_mode=...)`:

- `truecolor` (default) — `\x1b[38;2;R;G;Bm\x1b[0m▀`; byte-identical to the
  original output.
- `256` — `\x1b[38;5;Nm\x1b[0m▀`, where `N = rgb_to_256(jittered rgb)` is
  the nearest color in the standard 256-color palette (16 base colors,
  6x6x6 cube, 24-step grayscale ramp). Exact ties prefer the cube color
  (black → 16, white → 231).
- `none` — plain `▀`, no ANSI escapes.

Terminal capability is detected by `detect_color_mode(env=None)`:
`COLORTERM` containing `truecolor`/`24bit` (case-insensitive) wins and
yields `truecolor`; otherwise `TERM` containing `256color` yields `256`;
otherwise `none`.

CLI: `--color {truecolor,256,none}` forces the mode. Without the flag, a
TTY auto-detects via `COLORTERM`/`TERM`, and headless (non-TTY) output
stays `truecolor` (the existing contract). All other flags are unchanged.

## Licking flame shape (CC-113)

The flame body is not a solid cone. Two mechanisms:

- **Internal gaps / tongues:** in the lower body (rows
  `y >= h * GAP_ROW_FRACTION`), each rising cell skips diffusion with
  probability `GAP_PROB` — a cold pocket. Gaps streak slightly upward
  (a killed cell feeds zero to the row above), so the body shows licking
  tongues with blank cells strictly between colored ones; the upper rows
  stay coherent, keeping the tapered cone silhouette and letting heat
  still rise to the top rows.
- **No edge contact:** base-row ignitions whose heat falls below the
  blank threshold are dropped, so the leftmost/rightmost colored base
  cells never sit in the terminal edge columns (the base is a ragged,
  inset line).

Unchanged: tapering cone, blue combustion base, white-hot core,
per-frame flicker, smoke, per-cell jitter, determinism.
