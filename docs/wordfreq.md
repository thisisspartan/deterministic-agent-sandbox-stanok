# wordfreq

A small, deterministic word-frequency CLI (Python 3.11 stdlib only).

## What it does

Reads text from a file argument or from stdin, tokenizes it into words,
counts frequencies, and prints one `<word> <count>` line per distinct word
(single space, no header, no trailing spaces).

## How to run

```
python3 src/wordfreq.py FILE     # read from FILE
python3 src/wordfreq.py < text   # read from stdin (FILE omitted)
```

## Tokenization

The text is lowercased; a "word" is a maximal run of ASCII letters or
digits (`[a-z0-9]+`). Everything else — punctuation, whitespace, non-ASCII
characters — is a separator and is dropped.

## Sort order

Lines are sorted by count **descending**, then by word **ascending**
(lexicographic).

## Exit codes

- `0` — success (empty input prints nothing and still exits 0);
- `2` — FILE given but missing/unreadable (error message on stderr).

## Module API

`src/wordfreq.py` exposes `tokenize(text)`, `frequencies(tokens)`,
`format_report(freq)`, and `main(argv=None) -> int`, all importable for
tests.
