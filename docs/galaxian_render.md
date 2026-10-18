# galaxian_render — module contract (CC-294)

A pure terminal renderer: engine state -> one half-block frame string.
stdlib only; `src.galaxian_engine` is NOT imported — state attributes are
read duck-typed (R1: `width, height, score, wave, lives, player_x,
player_alive, enemies(kind/mode/x/y/explode), bullets, bombs, stars,
game_over`). No consumer yet: the terminal CLI arrives with CC-295.

Tests: `bash scripts/run.sh test tests/galaxian_render_test.py`.

## API (names pinned)

```
render_frame(state) -> str
```

Exactly `state.height // 2 + 2` lines joined by `"\n"`, no trailing `"\n"`:

- line 0 — the border: `width` segments, fg == bg == BORDER, glyph `" "`;
- lines `1 .. height//2` — half-block rows, one cell per column `x`,
  encoding pixel pairs `(2i, 2i+1)` of the `height x width` field;
- last line — the status (below).

Odd `state.height` -> `ValueError`. The field covers ALL `height` pixel
rows (the player at `y = height-2` must be renderable).

Purity: the state is never mutated; identical input -> identical output.
The frame contains no `ESC[H`, `ESC[2J`, `ESC[?25` (home/clear/cursor are
the CLI's responsibility).

## Segments

Every styled line is a concatenation of exactly `width` segments
`"\x1b[38;2;R;G;Bm\x1b[48;2;R;G;Bm" + glyph`, terminated by one `"\x1b[0m"`.

Half-block encoding per pair (top = pixel row `2i`, bottom = `2i+1`):
fg = color of the TOP pixel, bg = color of the BOTTOM pixel; glyph:

- top-only -> `"\u2580"` (▀, fg = top, bg = EMPTY);
- bottom-only -> `"\u2584"` (▄, fg = EMPTY, bg = bottom);
- both -> `"\u2580"` (▀, fg = top, bg = bottom);
- neither -> `" "` with SGR of EMPTY fg/bg.

## Status line

One prefix `"\x1b[38;2;220;220;220m\x1b[48;2;0;0;0m"`, then plain ASCII
`f"SC {score:06d}  LV {wave:02d}  LIVES {lives}"` truncated to `width`
or space-padded to exactly `width`, then `"\x1b[0m"` — at most one SGR
prefix and one reset in the line.

## Pixel masks (1 = colored pixel; anchor = mask top-left at `(x, y)`)

Masks may extend past the field; only in-field pixels are drawn (segment
count per line never changes). `player_alive=False` -> no player; `'F'`/`'D'`
enemies draw their kind mask.

- PLAYER 3x2 `"111"/"010"` at `(player_x, height-2)`, color PLAYER;
- kind1 3x2 `"101"/"111"`, color K1;
- kind2 3x2 `"111"/"101"`, color K2;
- kind3 5x3 `"10101"/"11111"/"01110"`, color K3;
- bullet 1x2 `"1"/"1"`, color BULLET; bomb 1x2 `"1"/"1"`, color BOMB;
- `'E'` explosion: kind1/2 -> 3x3 all-ones, kind3 -> 5x3 all-ones; color
  by explode parity: odd -> `(255,140,0)`, even -> `(255,60,60)`;
- star: a single TOP pixel of color STAR at cell `(x, y // 2)` (parity of
  `y` does not change the encoding).

Per-pixel priority: entity (enemy/bullet/bomb/player/explosion) > star > empty.

## Palette (pinned module constants)

`EMPTY (10,10,16)`, `BORDER (60,60,90)`, `PLAYER (235,235,235)`,
`K1 (0,200,0)`, `K2 (0,180,220)`, `K3 (255,60,60)`, `BULLET (235,235,235)`,
`BOMB (255,220,80)`, `STAR (90,90,110)`; explosion colors `EXPLODE_ODD
(255,140,0)` / `EXPLODE_EVEN (255,60,60)`; status fg/bg `(220,220,220)` /
`(0,0,0)`.
