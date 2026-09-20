# Terminal fire (`src/fire.py`)

Multicolored animated flame for the terminal, Python 3 stdlib only.

## Run / stop

```
python3 src/fire.py        # animate at ~30 FPS, flame centered in the terminal
# Ctrl-C stops cleanly: cursor restored (\x1b[?25h), ANSI state reset (\x1b[0m), exit 0
```

When stdout is not a TTY (pipe, CI) the module loads without animating —
this is how `scripts/run.sh smoke src/fire.py` works.

## How it works

1. **Simulation** (`_step_state`, seeded `random.Random`) — a 2D heat field
   in `[0, 1]` where y=0 is the top. Each tick: fuel is injected across a
   swaying band in the two bottom rows (per-column strength → multiple
   tongues), heat diffuses upward (`0.17` from the row below) with lateral
   spread, cools (`×0.9`), and is perturbed by per-column turbulence with
   occasional "lick" bursts. A global flicker factor (0.82–1.15) is applied
   per frame. The bottom rows with heat ≥ 0.25 are flagged as the
   **base zone** (combustion). Sparse deterministic **smoke particles**
   spawn just above the flame top, rise one row per tick and fade out.
2. **Palette** (`palette(heat, is_base)`) — pure multi-stop gradient,
   hot → cool: white-hot (255,255,240) → yellow (255,220,80) → orange
   (255,140,0) → red-orange (220,60,20) → red (160,30,10) → dark red
   (90,15,8) → `None` (zero heat = empty cell). Base-zone cells use a
   **blue** gradient (120,180,255 → 80,120,255).
3. **Renderer** (`render_frame`) — one ANSI frame per grid: 24-bit truecolor
   `\x1b[38;2;R;G;B m` + half-block `▀` (doubles vertical resolution), plain
   space for zero heat, faint gray (60,60,65) for smoke, and a small seeded
   per-cell jitter to break color banding. Frame dimensions match the grid.
4. **Loop** — only under `if __name__ == "__main__"`: hides the cursor,
   animates at 30 FPS, clears per frame, flame centered via
   `shutil.get_terminal_size()` (fallback 80×24), all output via `os.write`
   so the SIGINT handler can restore cursor/ANSI state safely.

## Color model (like a real flame)

- **Blue base** — the combustion zone where fresh fuel meets air;
- **White-hot core** — hottest cells just above the base;
- **Yellow → orange → red body** — cooling upward, red tips;
- **Faint gray smoke** — particles drifting above the flame.
