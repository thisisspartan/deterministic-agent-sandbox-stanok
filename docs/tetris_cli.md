# tetris_cli — module contract (CC-304)

Terminal boundary of the tetris console: consumes the pure engine
(`src.tetris_engine`) and the renderer (`src.tetris_render`). Parses CLI
flags, decodes stdin lines / keypresses into move/rotate/drop/quit
commands, paces ticks at 1/fps, and writes frames. stdlib only.

Tests: `bash scripts/run.sh test tests/tetris_cli_test.py` (reference)
and `tests/tetris_cli_contract_test.py` (calibrated oracle).

## Entry points (names pinned)

```
main(argv) -> int                    # also `python -m src.tetris_cli` from the repo root
run_loop(stdin, stdout, *, seed=1, width=10, height=20, fps=2.0, ticks=None,
         sleep=time.sleep, monotonic=time.monotonic) -> int
```

`import tetris_cli` bare (PYTHONPATH=src) works too. All parameters after
`stdin, stdout` are keyword-only. `run_loop` is the **single
frame-output point**: every frame the CLI ever writes goes through it.
`sleep`/`monotonic` are injectable keyword hooks for tests. TTY gates
call `isatty()` on the passed streams — never on the process globals.
Signals are unwound through the internal `_SignalQuit`.

## Flags and exit codes

| flag | type | default | invalid -> rc 2 (stdout stays empty) |
|---|---|---|---|
| `--seed` | int | 1 | — |
| `--width` | int | 10 | `< 2` |
| `--height` | int | 20 | `< 2` or odd |
| `--fps` | float | 2.0 | `<= 0` |
| `--ticks` | int | absent (interactive) | `< 1` |

Any unknown flag or unparseable value -> rc 2 (argparse usage on stderr,
stdout empty). A validated-out value additionally prints usage + an error
line on stderr. `--help` -> rc 0. All other exits are rc 0.

## Frame format

A frame is `render.render_board(state.board, active)` **unchanged**
followed by `"\n"`, where `active = (piece, x, y, piece_id)` (None when
no piece). Nothing else is ever written to stdout: no clear, no
cursor-hide, no diagnostics. The only other byte the CLI may emit is
`ESC[H` (`"\x1b[H"`) as a frame **prefix** in interactive TTY mode.

## Command decoding

Pipe/line mode (`parse_line`): an exact single-character line is one
command — `a` -> move(-1), `d` -> move(+1), `w` -> rotate(+1), `s` ->
soft drop, `" "` -> hard drop, `q` and `\x03` -> quit. A single trailing
`\r` is stripped; every other line (empty, multi-char) is junk and is
ignored. TTY mode (`parse_keys(data: bytes)`): in byte order, the 3-byte
CSI arrows `ESC[A/B/C/D` -> rotate / soft drop / move(+1) / move(-1)
(matched before single bytes), then the single-byte keys above; a lone
ESC or unmodelled escape is skipped byte by byte. Commands are applied
in order; a blocked move/rotate/drop keeps the state; the first quit
stops application.

## Bounded mode (`--ticks N`)

Read the stdin commands (a pipe/fake stream to EOF; a TTY stdin drained
once, non-blocking), apply them in order. A quit -> rc 0 with **NO
frames**, before any tick. Game over after a command -> the final frame,
rc 0. Otherwise exactly N ticks, exactly one frame after each; on game
over emit the final frame and stop (rc 0). NEVER emits `ESC[H`,
`ESC[2J`, or cursor-hide — even on a TTY stdout. Identical argv+stdin ->
byte-identical stdout.

## Interactive mode (no `--ticks`)

- stdin TTY -> termios raw: ICANON/ECHO cleared in lflag only (OPOST
  untouched), attributes deep-copied (cc list included) and restored with
  `TCSADRAIN` in `finally` on every exit path.
- stdin pipe -> line commands from a pending buffer (complete lines
  only); EOF ends the loop with rc 0.
- Period `1/fps`: drain all currently available commands, apply them,
  tick, emit one frame. Pacing uses the injected `monotonic`/`sleep`.
- stdout TTY -> **every frame, including the first**, is prefixed with
  `ESC[H`. Non-TTY stdout -> no homes. The cursor is never hidden.
- `q`, `\x03`, SIGINT or SIGTERM -> rc 0 (termios and the prior signal
  handlers restored). Game over (after a command or a tick) -> final
  frame emitted (with home if TTY), rc 0.

## Input plumbing

Real fds: `select(..., 0)` + `os.read` (a `b""` read is EOF). Streams
without a usable `fileno()` (test fakes) are drained via `read()` until
an empty read — for a duck-typed stream an empty read **is** EOF (the
interactive pipe contract: EOF terminates the loop). All reads are
non-blocking on real fds.
