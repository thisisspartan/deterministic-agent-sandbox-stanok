# csv_stats — deterministic CSV column-stats utility

Module: `src/csv_stats.py` (TASK-STANOK-CC-255). Standalone: library functions
plus a CLI (`python -m src.csv_stats`). stdlib only (`csv`, `statistics`,
`argparse`).

## Contract

- Parsing (stdlib `csv`): the **first row is the header** (column names). A row
  whose field count differs from the header's is **malformed and skipped** (a
  blank line has zero fields, so it is skipped too). Empty input or header-only
  input → empty result. Quoted fields (embedded commas, doubled quotes) are
  handled by the `csv` module; `\r\n` line endings are accepted.
- A cell is **numeric iff `float(cell)` succeeds** — integers, negatives,
  decimals, `.5`, `+7`, exponent notation (`1e3` → 1000.0), surrounding
  whitespace; `0x10`, `1e`, `""` and text are not numeric.
- `numeric_values(text, column) -> list[float]`: the numeric values of that
  column, in file order. Unknown column → `KeyError`.
- `column_stats(text) -> {column: {"min", "max", "mean", "median"}}`:
  statistics over the **numeric cells only** of each column (non-numeric cells
  in that column are skipped); a column with **zero numeric cells is absent**;
  iteration order is **by column name** (ascending). `mean` is the arithmetic
  mean, `median` the middle value for an odd count and the average of the two
  middle values for an even count (`statistics` semantics).
- `top_values(text, column, n) -> list[(value, count)]`:
  - counts **numeric values**, not cell text — `"1"`, `"1.0"` and `"1e0"` are
    the same value (one entry, count 3);
  - sorted by count **descending**; ties broken by **first occurrence** in the
    file (dict insertion order + a stable sort on the count alone);
  - `n < 1` → `[]`; `n` larger than the number of distinct values → all of
    them, sorted; unknown column → `KeyError`.
- `read_csv_text(path) -> str`: reads the file verbatim, UTF-8 explicitly
  (never through the locale), `newline=""` so the csv module sees the original
  line endings.

## Determinism

No randomness, no locale dependence (UTF-8 pinned explicitly), no time
dependence. Results iterate by column name. Same input → byte-identical output.

## CLI

```
python -m src.csv_stats <file> [-c COLUMN] [-n N]
```

- `<file>`: required input CSV file.
- No `-c`: print min/max/mean/median for **every numeric column**, columns
  sorted by name. With `-c COLUMN`: print the top-N values of that column.
- `-n N`: number of top values, default **10**; `N < 1` prints none.
- Invalid arguments (unknown flag, missing `-c`/`-n` value, non-integer `-n`,
  more than one positional file, no file, unreadable file, unknown `-c` column)
  → argparse standard behavior: **exit code 2**, message on stderr.

### Output format (pinned in tests/csv_stats_test.py)

Without `-c` (`<K>` = number of numeric columns; numbers are `repr()` — the
shortest form that round-trips exactly):

```
stats <K>
<column> min <min> max <max> mean <mean> median <median>
```

With `-c` (`<M> = min(n, number of distinct values)`):

```
top <M>
<count> <value>
```

Example — input:

```
score,score2,note
4,x,ok
2,1.5,ok
3,1.5,ok
bad,1.5,ok
```

`python -m src.csv_stats in.csv` (`note` has no numeric cell → absent):

```
stats 2
score min 2.0 max 4.0 mean 3.0 median 3.0
score2 min 1.5 max 1.5 mean 1.5 median 1.5
```

`python -m src.csv_stats in.csv -c score -n 2` (all counts are 1 → file order):

```
top 2
1 4.0
1 2.0
```

## Tests

`tests/csv_stats_test.py` (pytest, via `scripts/run.sh test ...`): empty and
header-only input → empty result; malformed rows skipped while valid rows are
still counted; quoted fields and CRLF; non-numeric cells skipped inside a
numeric column and a fully non-numeric column absent; numeric forms (integer,
negative, decimal, `1e3`, `.5`, `+7`, whitespace) with `0x10`/`1e` rejected;
median for odd and even counts and a single value; columns sorted by name;
top-N ordering, tie → first occurrence wins, value-keyed counting, `n < 1` →
`[]`, unknown column → `KeyError`; CLI via subprocess — byte-exact pinned
output for both modes and default N=10, byte-identical on a repeat run, rc=2
with a stderr message for invalid arguments and an unknown column; a 50-row
synthetic CSV (plus 5 malformed rows) whose stats are verified against values
computed by construction.
