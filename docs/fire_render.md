# fire_render — module contract (CC-288)

Pure renderer: heat grid -> ANSI frame string. No I/O, no time, no network,
no files, stdlib only. Second layer of the "console fire" wave: it does NOT
import `src/fire_engine` — it takes plain data (`list[list[int]]`, the shape
`fire_engine.grid` produces). The consumer of the frame (CLI/terminal) does
not exist yet; the seam is named and closed by ticket CC-289.

## Public API (pinned)

Exactly two public names: `render`, `palette`.

### `render(grid: Sequence[Sequence[int]]) -> str`

The single public frame path.

- Input: rows of int heat; equal row length is a **precondition** (not
  checked). Frame height = `len(grid)`, width = `len(grid[0])`.
- Output: exactly `len(grid)` lines joined by `"\r\n"`, **no trailing line
  break**. The frame contains **no** home/clear/cursor sequences
  (`"\x1b[H"`, `"\x1b[2J"`, …) — home/clear is the CLI's responsibility.
- Cell pixel: SGR truecolor background + space: `"\x1b[48;2;R;G;Bm "`
  (space U+0020). Each line contains exactly `width` cells. The only
  escapes in the frame are these SGR sequences.

### `palette(heat: int) -> tuple[int, int, int]`

DOOM-palette color.

- Input clamped to `[0, 255]` — negative and >255 never raise.
- Anchors, linear interpolation between neighbors (integer round-half-up,
  so anchors reproduce exactly):
  `0 → (0,0,0)`; `64 → (135,0,0)`; `128 → (255,60,0)`;
  `192 → (255,160,0)`; `255 → (255,255,0)`.

## Invariants

- Purity: `render` never mutates the input grid.
- Determinism: the same grid yields a byte-identical string; renders of
  different grids are independent (no hidden state).
- Palette monotonicity (observed invariant): for `heat1 < heat2`, the R
  and G components of `palette` do not decrease.
- No I/O, no import of `fire_engine`, no network. Stdlib only.

Aesthetics (flame beauty) are not part of the contract — only the listed
observable invariants are tested.

Tests: `tests/fire_render_test.py` (`bash scripts/run.sh test
tests/fire_render_test.py`).
