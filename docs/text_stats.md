# text_stats (TASK-STANOK-CC-235)

Word counting and top-frequency words over a plain string. Stdlib only:
`collections.Counter`.

## Contract

`src/text_stats.py`

- `word_count(text) -> int`
  The number of whitespace-separated words in `text`. Splitting uses
  `str.split()` semantics: any run of whitespace (spaces, tabs, newlines, CR)
  separates words and leading/trailing runs produce no empty tokens, so `""`
  and whitespace-only text give `0`. Case does not affect counting —
  `"A a"` is 2 words.

- `top_words(text, n) -> list[tuple[str, int]]`
  The `n` most frequent words as `(word, count)` pairs.
  - Words are lowercased before counting, so `"A a"` is one word `"a"` with
    count 2.
  - Order: count descending, then word ascending (ties break
    alphabetically) — `sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))`.
  - `n <= 0` -> `[]` (checked before any counting).
  - Fewer distinct words than `n` -> all of them are returned (the slice
    `[:n]` of a shorter list is the whole list).

## Tests

`tests/text_stats_test.py` (pytest, run via
`scripts/run.sh test tests/text_stats_test.py`)

- `word_count`: empty string, whitespace-only text, single word, repeated
  words counted, case irrelevance, multi-line text, leading/trailing whitespace.
- `top_words`: empty string, `n <= 0` (0 and negative), single word, counts of
  repeated words, case folding (`"A a"` -> `[("a", 2)]`), descending-count
  ordering, alphabetical tie-breaking (uniform and mixed distributions),
  truncation to `n`, `n` larger than the distinct-word count, multi-line text,
  and the exact `(str, int)` pair shape.
