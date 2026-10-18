# galaxian_cli — module contract (CC-295)

Terminal boundary of the Galaxian wave: consumes the pure engine
(`src.galaxian_engine`) and the renderer (`src.galaxian_render`). Parses CLI
flags, decodes keypresses into move/fire/quit commands, paces ticks at
1/fps, and writes frames. stdlib only.

Tests: `bash scripts/run.sh test tests/galaxian_cli_test.py`.

## Entry points (names pinned)

```
main(argv) -> int                    # also `python -m src.galaxian_cli` from the repo root
run_loop(stdin, stdout, seed=1, width=32, height=24, fps=8.0, ticks=None,
         *, sleep=time.sleep, monotonic=time.monotonic) -> int
```

`import galaxian_cli` bare (PYTHONPATH=src) works too. `run_loop` is the
**single frame-output point**: every frame the CLI ever writes goes through
it. `sleep`/`monotonic` are injectable keyword hooks for tests. TTY gates
call `isatty()` on the passed streams — never on the process globals.

## Flags and exit codes

| flag | type | default | invalid -> rc 2 (stdout stays empty) |
|---|---|---|---|
| `--seed` | int | 1 | — |
| `--width` | int | 32 | `< 12` |
| `--height` | int | 24 | `< 8` or odd |
| `--fps` | float | 8.0 | `<= 0` |
| `--ticks` | int | absent (interactive) | `< 1` |

Any unknown flag -> rc 2 (argparse usage on stderr, stdout empty).
`--help` -> rc 0. All other exits are rc 0.

## Frame format

A frame is `render.render_frame(state)` **unchanged** followed by `"\n"`.
Nothing else is ever written to stdout: no clear, no cursor-hide, no
diagnostics. The only other byte the CLI may emit is `ESC[H` (`"\x1b[H"`)
as a frame **prefix** in interactive TTY mode (see below).

## Key decoding (`parse_keys(data: bytes) -> list`)

In byte order: `a` / `ESC[D` -> `("move", -1)`; `d` / `ESC[C` ->
`("move", +1)`; space, `w`, `ESC[A` -> `("fire", None)`; `q` and `\x03` ->
`("quit", None)`. Arrow keys are the 3-byte CSI sequences (matched before
single bytes); a lone ESC or unmodelled escape is skipped byte by byte;
other bytes are ignored. Commands are applied in order; the first quit
stops application.

## Bounded mode (`--ticks N`)

Drain stdin once, non-blocking; apply commands in order. A quit -> rc 0
with **NO frames**. Otherwise exactly N ticks, exactly one frame after
each; on game over emit the final frame and stop (rc 0). NEVER emits
`ESC[H`, `ESC[2J`, or cursor-hide — even on a TTY stdout. Identical
argv+stdin -> byte-identical stdout.

## Interactive mode (no `--ticks`)

- stdin TTY -> termios raw: ICANON/ECHO cleared in lflag only (OPOST
  untouched), attributes deep-copied (cc list included) and restored with
  `TCSADRAIN` in `finally` on every exit path.
- Period `1/fps`: drain all currently available commands, apply them,
  tick, emit one frame. Pacing uses the injected `monotonic`/`sleep`.
- stdout TTY -> **every frame, including the first**, is prefixed with
  `ESC[H`. Non-TTY stdout -> no homes; the stream is byte-identical to
  the TTY stream with the homes removed. The cursor is never hidden.
- `q`, `\x03`, or SIGINT -> rc 0 (termios and the prior SIGINT handler
  restored). Game over -> final frame emitted (with home if TTY), rc 0.
- EOF on a non-TTY stdin ends the loop; a duck-typed stream without a
  real fd never signals EOF (an empty read means "nothing available
  right now").

## Input plumbing

Real fds: `select(..., 0)` + `os.read` (a `b""` read is EOF). Streams
without a usable `fileno()` (test fakes) are drained via `read(1)` until
an empty read. All reads are non-blocking.
