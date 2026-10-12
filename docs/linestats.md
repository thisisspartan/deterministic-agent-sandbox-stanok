# linestats (TASK-STANOK-CC-246)

Line statistics over a plain string. Stdlib only, pure text: no file or socket
I/O, no imports at all.

## Contract

`src/linestats.py`

All three functions share one line-splitting rule (`_lines`, built on
`str.splitlines()`): LF, CRLF and CR terminate a line and are never part of
it. A trailing terminator ends the last line and does **not** produce a
trailing empty line. So `""` -> `[]`, `"a\n"` -> `["a"]`, and LF and CRLF
input give identical results.

- `line_count(text) -> int`
  The number of lines. `""` -> `0`. A trailing newline adds nothing:
  `"a\nb\n"` -> `2`. Interior empty lines are lines: `"a\n\nb"` -> `3`.
  A lone `"\n"` is one (empty) line -> `1`.

- `blank_line_count(text) -> int`
  The number of lines that are empty or contain nothing but whitespace
  (`not line.strip()`). `"a\n   \nb"` -> `1`, `"  \n\t\n"` -> `2`.
  Whitespace *inside* a line does not make it blank (`"a b"` is not blank).
  `"a\n"` has no second line -> `0`, while `"a\n   "` has a whitespace-only
  second line -> `1`.

- `longest_line(text) -> str`
  The longest line measured in **characters** (`len` of the `str`, i.e.
  Unicode code points — `"café"` is 4, not 5 bytes; an emoji is 1).
  Ties resolve to the FIRST occurrence: the running best is replaced only on a
  strict `>`, so a later line of equal length never wins. The returned line
  never carries a terminator. `""` -> `""` (no lines); text made only of
  newlines -> `""` (every line is empty).

## Tests

`tests/linestats_test.py` (pytest, run via
`scripts/run.sh test tests/linestats_test.py`)

- `line_count`: empty text, single line with and without a trailing newline,
  multiple lines, a lone `"\n"` and `"\n\n"`, interior empty lines, CRLF vs LF
  equality (including a mixed block), a multi-line CRLF block.
- `blank_line_count`: empty text, no blank lines, empty lines, whitespace-only
  lines (spaces / tabs / mixed), a whitespace-only final line vs a bare
  trailing newline, CRLF matching LF, inner whitespace not counting as blank.
- `longest_line`: empty text, single line, exact value, terminators excluded,
  first-wins tie-breaking (uniform, mixed, and across a CRLF/LF mix),
  all-empty text, a whitespace-only line winning on length, and Unicode
  counted by characters (accented Latin, Cyrillic, emoji) including a
  character-tie across different byte counts.
