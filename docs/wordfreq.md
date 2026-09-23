# wordfreq — deterministic word-frequency CLI

`src/wordfreq.py` (Python 3.11 stdlib only). Reads text from a file
argument or stdin, tokenizes it into words (maximal runs of `[a-z0-9]`
after lowercasing), and prints one `<word> <count>` line per distinct
word, sorted by count descending then word ascending.

## Module API

- `tokenize(text: str) -> list[str]` — lowercased word tokens, in order.
- `frequencies(tokens: list[str]) -> dict[str, int]` — word -> count.
- `format_report(freq: dict[str, int]) -> str` — sorted `<word> <count>`
  lines joined by `\n`, no trailing newline; empty dict -> `""`.
- `top_n(freq: dict[str, int], n: int) -> list[tuple[str, int]]` — the
  top `n` entries in report order (count descending, then word
  ascending — the same order `format_report` uses). `n <= 0` -> `[]`;
  `n >= len(freq)` -> all entries; empty dict -> `[]`.
- `main(argv: list[str] | None = None) -> int` — CLI entry point.

## CLI

```
wordfreq [--top N] [file]
```

- `[file]` — input file; if omitted, stdin is read.
- `--top N` — print only the top `N` report lines, i.e.
  `format_report(top_n(freq, N))`. Without `--top`, the full report is
  printed (behavior unchanged).
- Exit codes:
  - `0` — success.
  - `2` — file missing/unreadable, **or** `--top` given a non-integer
    argument (e.g. `--top abc`) or a non-positive integer (e.g.
    `--top 0`, `--top -1`); in both `--top` cases a message is written
    to stderr.

## Examples

```
$ printf 'one two one three two one\n' > in.txt
$ wordfreq in.txt
one 3
two 2
three 1
$ wordfreq --top 2 in.txt
one 3
two 2
$ wordfreq --top 0 in.txt
wordfreq: --top must be a positive integer, got 0   # exit 2
```
