# text_stats — deterministic text-stats utility

Module: `src/text_stats.py` (TASK-STANOK-CC-254). Standalone: library
functions plus a CLI (`python -m src.text_stats`). stdlib only.

## Contract

- `count_stats(text) -> (lines, words, characters)`:
  - characters: every character including newlines — `len(text)`;
  - lines: `str.splitlines()` semantics — a trailing newline does NOT add an
    empty line; `\r\n` is one line break; a lone `\r` is a line break too;
    blank lines ARE lines;
  - words: maximal runs of non-whitespace characters — `str.split()`
    semantics (`\r` is whitespace, never part of a word).
- `top_words(text, n) -> list[(word, count)]`:
  - sorted by count **descending**; ties broken by **first occurrence** in
    the text (dict insertion order + a stable sort on the count alone) —
    fully deterministic;
  - case is preserved, no case folding (`"Привет"` and `"привет"` are
    distinct words);
  - `n < 1` → `[]`; `n` larger than the number of distinct words → all of
    them, sorted.
- `read_text(path=None) -> str`:
  - `path=None` reads all of **stdin** (raw bytes decoded as UTF-8
    explicitly — never through the locale);
  - a path reads that file verbatim (`open(..., encoding="utf-8",
    newline="")` — no newline translation, `\r\n` stays `\r\n` and counts
    as characters).

## Determinism

No randomness, no locale dependence (UTF-8 is pinned explicitly), no time
dependence. Same input → byte-identical output.

## CLI

```
python -m src.text_stats [file] [-n N]
```

- `file` optional: absent → read all of stdin; present → read that file.
- `-n N`: number of top words, default **10**; `N < 1` prints none.
- Invalid arguments (unknown flag, non-integer or missing `-n` value, more
  than one positional file) → argparse standard behavior: **exit code 2**,
  usage/message on stderr.

### Output format (pinned in tests/text_stats_test.py)

```
lines <L>
words <W>
chars <C>
top <M>
<count> <word>        ← M = min(n, number of distinct words) lines
```

Every line ends with `\n`; word lines are `<count> <word>` (a word never
contains whitespace, so one per line is unambiguous). Example — input
`"foo bar foo baz\n"`, `-n 2`:

```
lines 1
words 4
chars 16
top 2
2 foo
1 bar
```

## Tests

`tests/text_stats_test.py` (pytest, via `scripts/run.sh test ...`): empty
input (all zeros, empty top list); basic and trailing-newline counting;
Cyrillic/Unicode counting with case preserved; CRLF (splitlines line counts,
`\r` never in a word, raw file read); top-N ordering, tie → first
occurrence wins, `n < 1` → `[]`; CLI via subprocess — pinned byte-exact
output for file and stdin input and default N=10, rc=2 with stderr message
for invalid arguments; a 10 309-character synthetic text (500 lines, 1746
words) with counts and top-6 verified against values computed by
construction.
