"""Reference tests for TASK-STANOK-CC-255: src/csv_stats.py — a deterministic
CSV column-stats utility (parsing, numeric column stats, top-N values, CLI).

Contract pinned here and in docs/csv_stats.md:
- first row = header; a row whose field count differs from the header's is
  malformed and skipped;
- a cell is numeric iff float(cell) succeeds; stats (min/max/mean/median) are
  computed over the numeric cells of a column only; a column with zero numeric
  cells is absent from the result;
- top_values(text, column, n) -> [(value, count)] sorted by count descending,
  ties broken by first occurrence in the file; n < 1 -> []; unknown column ->
  KeyError;
- results iterate by column name (deterministic).

CLI: `python -m src.csv_stats <file> [-c COLUMN] [-n N]` (default N=10).
Output format (byte-identical for the same input):

    stats <K>                                       (no -c)
    <column> min <min> max <max> mean <mean> median <median>

    top <M>                                         (with -c)
    <count> <value>

Invalid arguments (unknown flag, missing value, non-integer -n, missing file,
unknown -c column) -> exit code 2, message on stderr.
"""

import pathlib
import subprocess
import sys

import pytest

import csv_stats

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def run_cli(*args):
    """Run the CLI as a subprocess from the repo root (module path src.csv_stats)."""
    return subprocess.run(
        [sys.executable, "-m", "src.csv_stats", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# --- parsing: empty / header-only / malformed -------------------------------------


def test_empty_and_header_only_input_produce_empty_results():
    # No input at all, and input that is only a header, have no data rows:
    # the result is empty.
    assert csv_stats.column_stats("") == {}
    assert csv_stats.column_stats("\n") == {}
    assert csv_stats.column_stats("a,b\n") == {}
    assert csv_stats.column_stats("a,b") == {}  # header without a trailing newline
    # A column that exists but has no numeric cells -> empty top list.
    assert csv_stats.top_values("a,b\n", "a", 3) == []
    assert csv_stats.numeric_values("a,b\n", "a") == []
    # With no header at all there is no such column.
    with pytest.raises(KeyError):
        csv_stats.top_values("", "a", 3)


def test_malformed_rows_are_skipped_and_valid_rows_still_counted():
    text = (
        "a,b\n"
        "1,10\n"
        "2,20,extra\n"  # too many fields -> skipped
        "3\n"  # too few fields -> skipped
        ",\n"  # right shape, both cells non-numeric -> contributes nothing
        "\n"  # blank line -> zero fields -> skipped
        "4,40\n"
    )
    # Only the two well-formed rows contribute.
    assert csv_stats.column_stats(text) == {
        "a": {"min": 1.0, "max": 4.0, "mean": 2.5, "median": 2.5},
        "b": {"min": 10.0, "max": 40.0, "mean": 25.0, "median": 25.0},
    }
    assert csv_stats.numeric_values(text, "a") == [1.0, 4.0]


def test_quoted_fields_and_crlf_are_parsed_by_the_stdlib_csv_module():
    text = 'name,val\r\n"quoted, name",5\r\n"with ""quotes""",7\r\n'
    stats = csv_stats.column_stats(text)
    assert list(stats) == ["val"]
    assert stats["val"] == {"min": 5.0, "max": 7.0, "mean": 6.0, "median": 6.0}
    # The quoted comma stays inside one field: the row has exactly 2 fields.
    assert csv_stats.top_values(text, "val", 5) == [(5.0, 1), (7.0, 1)]


# --- numeric vs non-numeric cells ------------------------------------------------


def test_non_numeric_cells_in_a_numeric_column_are_skipped():
    text = (
        "v,note\n"
        "1,hello\n"
        "oops,2\n"  # 'oops' skipped in v; 'note' gets a numeric cell here
        "3,\n"  # empty cell is not numeric
        "-4,world\n"
    )
    stats = csv_stats.column_stats(text)
    assert list(stats) == ["note", "v"]  # iteration order is by column name
    assert stats["v"] == {"min": -4.0, "max": 3.0, "mean": 0.0, "median": 1.0}
    assert stats["note"] == {"min": 2.0, "max": 2.0, "mean": 2.0, "median": 2.0}
    assert csv_stats.numeric_values(text, "v") == [1.0, 3.0, -4.0]


def test_fully_non_numeric_column_is_absent_from_the_result():
    text = "num,name\n1,alice\n2,bob\n3,carol\n"
    stats = csv_stats.column_stats(text)
    assert list(stats) == ["num"]
    assert "name" not in stats
    assert csv_stats.numeric_values(text, "name") == []
    assert csv_stats.top_values(text, "name", 5) == []


def test_numeric_forms_integers_negatives_decimals_and_exponent_notation():
    text = (
        "n\n"
        "1\n"  # integer
        "-2\n"  # negative integer
        "3.5\n"  # decimal
        "1e3\n"  # exponent notation -> 1000.0
        "-1.5e-2\n"  # negative exponent -> -0.015
        ".5\n"  # leading-dot decimal
        "+7\n"  # explicit sign
        " 8 \n"  # float() tolerates surrounding whitespace
        "0x10\n"  # hex literal: float() fails -> not numeric
        "1,2\n"  # two fields -> malformed row, skipped entirely
        "1e\n"  # malformed exponent -> not numeric
    )
    assert csv_stats.numeric_values(text, "n") == [
        1.0,
        -2.0,
        3.5,
        1000.0,
        -0.015,
        0.5,
        7.0,
        8.0,
    ]
    stats = csv_stats.column_stats(text)["n"]
    assert stats["min"] == -2.0
    assert stats["max"] == 1000.0


# --- stats: min/max/mean/median ---------------------------------------------------


def test_median_odd_count_is_the_middle_value_even_count_averages_the_two_middle():
    odd = "c\n5\n1\n9\n"  # sorted [1, 5, 9] -> middle is 5
    assert csv_stats.column_stats(odd)["c"]["median"] == 5.0
    even = "c\n5\n1\n9\n2\n"  # sorted [1, 2, 5, 9] -> (2 + 5) / 2 = 3.5
    assert csv_stats.column_stats(even)["c"]["median"] == 3.5
    # A single numeric cell: every statistic is that value.
    assert csv_stats.column_stats("c\n7\n")["c"] == {
        "min": 7.0,
        "max": 7.0,
        "mean": 7.0,
        "median": 7.0,
    }
    # mean is the arithmetic mean over the numeric cells only.
    assert csv_stats.column_stats("c\n1\n2\n6\n")["c"]["mean"] == 3.0


def test_column_stats_keys_are_sorted_by_column_name():
    text = "zeta,alpha,mid\n1,2,3\n"
    assert list(csv_stats.column_stats(text)) == ["alpha", "mid", "zeta"]


# --- top-N values -----------------------------------------------------------------


def test_top_values_sorted_by_count_desc_and_ties_broken_by_first_occurrence():
    text = (
        "c\n"
        "3\n"
        "1\n"
        "3\n"
        "2\n"
        "1\n"
        "3\n"
        "oops\n"  # non-numeric -> not counted
    )
    assert csv_stats.top_values(text, "c", 2) == [(3.0, 3), (1.0, 2)]
    # n larger than the number of distinct values -> all of them, sorted.
    assert csv_stats.top_values(text, "c", 10) == [(3.0, 3), (1.0, 2), (2.0, 1)]
    # Equal counts: the value that appears first in the file wins (1 before 2).
    tie = "c\n1\n2\n1\n2\n"
    assert csv_stats.top_values(tie, "c", 2) == [(1.0, 2), (2.0, 2)]
    assert csv_stats.top_values(tie, "c", 1) == [(1.0, 2)]


def test_top_values_counts_numeric_values_not_cell_text_and_rejects_bad_arguments():
    # 1, 1.0 and 1e0 are the same numeric value -> one entry with count 3.
    assert csv_stats.top_values("c\n1\n1.0\n1e0\n", "c", 5) == [(1.0, 3)]
    # n < 1 -> empty list.
    text = "c\n1\n1\n"
    assert csv_stats.top_values(text, "c", 0) == []
    assert csv_stats.top_values(text, "c", -1) == []
    assert csv_stats.top_values(text, "c", -100) == []
    # Unknown column -> KeyError (also when the column has no numeric cells).
    with pytest.raises(KeyError):
        csv_stats.top_values(text, "nope", 3)
    with pytest.raises(KeyError):
        csv_stats.numeric_values(text, "nope")


# --- CLI ----------------------------------------------------------------------------


CLI_CSV = "score,score2,note\n4,x,ok\n2,1.5,ok\n3,1.5,ok\nbad,1.5,ok\n"

STATS_OUT = (
    "stats 2\n"
    "score min 2.0 max 4.0 mean 3.0 median 3.0\n"
    "score2 min 1.5 max 1.5 mean 1.5 median 1.5\n"
)


def test_cli_without_column_prints_stats_of_every_numeric_column(tmp_path):
    p = tmp_path / "in.csv"
    p.write_text(CLI_CSV, encoding="utf-8")
    proc = run_cli(str(p))
    assert proc.returncode == 0, proc.stderr
    # 'note' has no numeric cell -> absent; columns sorted by name.
    assert proc.stdout == STATS_OUT
    # Deterministic: the same input twice -> byte-identical output.
    assert run_cli(str(p)).stdout == proc.stdout


def test_cli_with_column_prints_top_n_values_default_n_is_10(tmp_path):
    p = tmp_path / "in.csv"
    p.write_text(CLI_CSV, encoding="utf-8")
    proc = run_cli(str(p), "-c", "score", "-n", "2")
    assert proc.returncode == 0, proc.stderr
    # All three values have count 1 -> first-occurrence order (4, 2, 3), cut to 2.
    assert proc.stdout == "top 2\n1 4.0\n1 2.0\n"

    # Default N=10 -> every distinct value of the column.
    proc = run_cli(str(p), "-c", "score")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "top 3\n1 4.0\n1 2.0\n1 3.0\n"

    # A column whose numeric cells are all equal.
    proc = run_cli(str(p), "-c", "score2", "-n", "1")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "top 1\n3 1.5\n"


def test_cli_no_numeric_columns_and_no_such_column(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("a,b\nx,y\n", encoding="utf-8")
    proc = run_cli(str(empty))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "stats 0\n"

    p = tmp_path / "in.csv"
    p.write_text(CLI_CSV, encoding="utf-8")
    proc = run_cli(str(p), "-c", "nope")
    assert proc.returncode == 2
    assert proc.stderr.strip() != ""


@pytest.mark.parametrize(
    "args",
    [
        ["--bogus"],  # unknown flag
        ["-c"],  # -c without a value
        ["-n", "abc"],  # -n is not an integer
        ["-n"],  # -n without a value
        ["a.csv", "b.csv"],  # more than one positional file
        [],  # no input file at all
    ],
)
def test_cli_invalid_arguments_exit_2_with_message_on_stderr(tmp_path, args):
    p = tmp_path / "a.csv"
    p.write_text(CLI_CSV, encoding="utf-8")
    argv = [str(p) if a == "a.csv" else a for a in args]
    proc = run_cli(*argv)
    assert proc.returncode == 2
    assert proc.stderr.strip() != ""


# --- larger input (~50 rows synthetic) ----------------------------------------------

ROWS = 50


def _synthetic_csv():
    """Deterministic 50-row CSV: columns x (1..50), y (-1.5..-50.5), name (text),
    plus one malformed 5-field row after every 10th data row."""
    out = ["x,y,name"]
    for i in range(1, ROWS + 1):
        out.append(f"{i},{-i}.5,name{i}")
        if i % 10 == 0:
            out.append("malformed,row,has,too,many")
    return "\n".join(out) + "\n"


def test_large_synthetic_input_all_stats_verified_against_expected_values():
    text = _synthetic_csv()
    stats = csv_stats.column_stats(text)
    # 'name' is fully non-numeric -> absent; the 5 malformed rows are skipped.
    assert list(stats) == ["x", "y"]
    # x = 1..50 -> min 1, max 50, mean (1+50)/2, median (25+26)/2.
    assert stats["x"] == {
        "min": 1.0,
        "max": 50.0,
        "mean": 25.5,
        "median": 25.5,
    }
    # y = -(1.5)..-(50.5) -> mean -(1300/50), median (-26.5 + -25.5)/2.
    assert stats["y"] == {
        "min": -50.5,
        "max": -1.5,
        "mean": -26.0,
        "median": -26.0,
    }
    # Every value appears once -> all counts 1 -> file order.
    assert csv_stats.top_values(text, "x", 3) == [(1.0, 1), (2.0, 1), (3.0, 1)]
    assert csv_stats.top_values(text, "y", 2) == [(-1.5, 1), (-2.5, 1)]
    assert len(csv_stats.numeric_values(text, "x")) == ROWS


def test_cli_on_large_synthetic_input_is_deterministic_and_matches_library(tmp_path):
    p = tmp_path / "big.csv"
    p.write_text(_synthetic_csv(), encoding="utf-8")
    proc = run_cli(str(p))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        "stats 2\n"
        "x min 1.0 max 50.0 mean 25.5 median 25.5\n"
        "y min -50.5 max -1.5 mean -26.0 median -26.0\n"
    )
    assert run_cli(str(p)).stdout == proc.stdout  # byte-identical on a second run
