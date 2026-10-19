# water_cli — module contract (CC-301)

Terminal boundary of the water surface: consumes the pure engine
(`src.water_engine`) and the renderer (`src.water_render`). Parses CLI flags,
then writes frames — either as a plain byte stream (pipe mode) or as an
alt-buffer animation on a real terminal (TTY mode). stdlib only.

Tests: `bash scripts/run.sh test tests/water_cli_test.py`.

## Entry points (names pinned)

```
main(argv) -> int                    # also `python -m src.water_cli` from the repo root
run_loop(stdin, stdout, *, seed, width, height, frames, fps,
         sleep=time.sleep, monotonic=time.monotonic) -> int
_SignalQuit                         # internal: unwinds the frame loop to rc 0
```

`import water_cli` bare (PYTHONPATH=src) works too. `run_loop` is the
**single frame-output point**: every byte of every frame the CLI writes goes
through it. `frames` is an int >= 1 (exactly N frames) or None (run until
`_SignalQuit`). `sleep`/`monotonic` are injectable keyword hooks. The mode
gate calls `isatty()` on the passed stdout — never on the process globals.

## Flags and exit codes (C1)

| flag | type | default | invalid -> rc 2 (argparse usage on stderr, stdout empty) |
|---|---|---|---|
| `--width` | int | terminal columns, else 80 | outside `12..200` |
| `--height` | int | 24 | outside `4..60` |
| `--seed` | int | 1 | `< 0` |
| `--frames` | int | absent | `< 1` |
| `--fps` | number | 24 | outside `1..60` |

Any out-of-range value or unknown flag -> rc 2, usage on stderr, stdout
stays empty. `--help` -> usage on stdout, rc 0. `--frames` absent with a
non-TTY stdout -> rc 3 (see C5). Every other exit is rc 0, including a run
ended by SIGINT/SIGTERM.

## Pipe mode (C2) — stdout is not a TTY and `--frames N` is given

Exactly N frames, one `print` per frame: `render.render_frame(engine.frame_state(
engine.make_params(seed), t, width), width, height)` for `t = 0..N-1`, each
followed by `"\n"` — so exactly `N * height` lines, the stream ending in one
`"\n"`. The frame bytes are **identical** to the renderer's own output; the
CLI adds nothing to them. No alt-buffer (`ESC[?1049h/l`), no cursor
hide/show (`ESC[?25l/h`), no `ESC[H` — none of those bytes ever appear in
pipe mode. Identical argv -> byte-identical stdout. rc 0.

## TTY mode (C3) — stdout is a TTY

Protocol, in this order and with these exact counts:

1. at the start, once: `ESC[?1049h` then `ESC[?25l`;
2. each frame — **including the first** — prefixed with `ESC[H` (home only,
   no 1049/25 codes), payload = `render.render_frame(...)` unchanged;
3. at the end, once: `ESC[?1049l` then `ESC[?25h`, and nothing after them.

Frames are paced at a fixed timestep `1/fps` using the injected
`monotonic`/`sleep` (the next deadline is advanced by the period, so pacing
does not drift). `--frames N` stops after N frames; without `--frames` the
loop runs until a signal. On **every** exit path — normal end, `--frames`
budget, or signal — the teardown pair is written exactly once, and those
four protocol bytes appear nowhere else in the stream.

## Signals (C4)

SIGINT and SIGTERM are handled: the handler raises `_SignalQuit`, which
unwinds the frame loop, runs the C3 teardown exactly once (not twice, not
zero times), restores the previous signal handlers, and returns rc 0.

## No terminal, no frame count (C5)

stdout is not a TTY and `--frames` was not given: nothing is written to
stdout, stderr gets the line `water: no terminal and no --frames`, rc 3.
(`run_loop` with a non-TTY stdout and `frames=None` returns the same 3.)
