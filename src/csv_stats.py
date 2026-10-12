"""Deterministic CSV column-stats utility (TASK-STANOK-CC-255).

Parsing semantics (pinned in tests/csv_stats_test.py and docs/csv_stats.md):
- the first row is the header (column names); a row whose field count differs
  from the header's is malformed and skipped;
- a cell is numeric iff float(cell) succeeds; min/max/mean/median are computed
  over the numeric cells of a column only; a column with zero numeric cells is
  absent from the result;
- empty input or header-only input -> empty result.

top_values(text, column, n) returns [(value, count), ...] sorted by count
descending; ties are broken by first occurrence in the file (dict insertion
order + a stable sort). Counting is by numeric value, so "1", "1.0" and "1e0"
are one value. n < 1 yields []; an unknown column raises KeyError. No
randomness, no locale or time dependence; results iterate by column name.

CLI: `python -m src.csv_stats <file> [-c COLUMN] [-n N]` (default N=10).
Invalid arguments (unknown flag, missing value, non-integer -n, missing file,
unknown -c column) -> argparse standard behavior (exit 2, message on stderr).
Output format (deterministic, byte-identical for the same input):

    stats <K>                                          (no -c)
    <column> min <min> max <max> mean <mean> median <median>

    top <M>                                            (with -c)
    <count> <value>

Numbers are printed with repr(), the shortest form that round-trips exactly.
"""

import argparse
import csv
import io
import statistics
import sys


def _parse(text):
    """Return (header, rows): the header row and the rows whose field count
    matches it. Empty input yields (None, []); a blank line has zero fields and
    is therefore malformed unless the header is empty too."""
    reader = csv.reader(io.StringIO(text, newline=""))
    header = None
    rows = []
    for row in reader:
        if header is None:
            header = row
        elif len(row) == len(header):
            rows.append(row)
    return header, rows


def _numeric_by_column(text):
    """Map each header column to the list of its numeric cell values, in file
    order. Columns with no numeric cell map to an empty list."""
    header, rows = _parse(text)
    if header is None:
        return {}
    values = {name: [] for name in header}
    for row in rows:
        for name, cell in zip(header, row):
            try:
                values[name].append(float(cell))
            except ValueError:
                continue
    return values


def numeric_values(text, column):
    """The numeric values of `column`, in file order. Unknown column -> KeyError."""
    values = _numeric_by_column(text)
    if column not in values:
        raise KeyError(column)
    return list(values[column])


def column_stats(text):
    """{column: {"min", "max", "mean", "median"}} over the numeric cells of each
    column, columns sorted by name; a column with no numeric cell is absent."""
    stats = {}
    for column, values in sorted(_numeric_by_column(text).items()):
        if not values:
            continue
        stats[column] = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
        }
    return stats


def top_values(text, column, n):
    """Top-N values of `column` as [(value, count), ...]: count descending, ties
    by first occurrence in the file. n < 1 -> []; unknown column -> KeyError."""
    values = numeric_values(text, column)
    if n < 1:
        return []
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    # dict preserves first-occurrence order; the sort is stable and keyed only
    # on the count, so equal counts keep that order.
    return sorted(counts.items(), key=lambda item: -item[1])[:n]


def format_stats(stats):
    """Render the pinned stats report: `stats <K>`, then one line per column."""
    out = [f"stats {len(stats)}"]
    for column, s in stats.items():
        out.append(
            f"{column} min {s['min']!r} max {s['max']!r} "
            f"mean {s['mean']!r} median {s['median']!r}"
        )
    return "\n".join(out) + "\n"


def format_top(top):
    """Render the pinned top-N report: `top <M>`, then `<count> <value>` lines."""
    out = [f"top {len(top)}"]
    out.extend(f"{count} {value!r}" for value, count in top)
    return "\n".join(out) + "\n"


def read_csv_text(path):
    """Read the CSV file verbatim: UTF-8 explicitly (never through the locale),
    newline="" so the csv module sees the original line endings."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="csv_stats",
        description="Report min/max/mean/median per numeric CSV column, "
        "or the top-N values of one column.",
    )
    parser.add_argument("file", help="input CSV file (its first row is the header)")
    parser.add_argument(
        "-c",
        metavar="COLUMN",
        help="print the top-N values of this column instead of the column stats",
    )
    parser.add_argument(
        "-n",
        type=int,
        default=10,
        metavar="N",
        help="number of top values to print (default: 10; n < 1 prints none)",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        text = read_csv_text(args.file)
    except OSError as exc:
        parser.error(f"cannot read {args.file}: {exc.strerror or exc}")
    if args.c is None:
        sys.stdout.write(format_stats(column_stats(text)))
    else:
        try:
            top = top_values(text, args.c, args.n)
        except KeyError:
            parser.error(f"unknown column: {args.c}")
        sys.stdout.write(format_top(top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
