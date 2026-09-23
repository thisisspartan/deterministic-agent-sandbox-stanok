"""Contract tests for the top-N report (CC-118): top_n + --top N CLI flag.

Covers the top_n() module API (report order, tie-break, n<=0, n>=len,
empty dict) and the CLI --top N flag (top-N stdout, exit-2 on bad N,
full-report regression without the flag).
"""

import wordfreq  # src is on sys.path via pythonpath=src in run.sh


# --- top_n -------------------------------------------------------------------

def test_top_n_basic():
    assert wordfreq.top_n({"a": 3, "b": 1, "c": 2}, 2) == [("a", 3), ("c", 2)]


def test_top_n_tie_break_word_ascending():
    # Equal counts -> word ascending, same order format_report uses.
    assert wordfreq.top_n({"b": 2, "a": 2, "c": 2}, 2) == [("a", 2), ("b", 2)]


def test_top_n_zero_and_negative():
    freq = {"a": 3, "b": 1}
    assert wordfreq.top_n(freq, 0) == []
    assert wordfreq.top_n(freq, -5) == []


def test_top_n_larger_than_freq_returns_all_in_report_order():
    freq = {"a": 3, "b": 1, "c": 2}
    assert wordfreq.top_n(freq, 100) == [("a", 3), ("c", 2), ("b", 1)]


def test_top_n_exact_boundary():
    freq = {"a": 3, "b": 1, "c": 2}
    assert wordfreq.top_n(freq, 3) == [("a", 3), ("c", 2), ("b", 1)]


def test_top_n_empty_dict():
    assert wordfreq.top_n({}, 3) == []


# --- CLI --top ----------------------------------------------------------------

def test_cli_top2_prints_only_top_lines(capsys, tmp_path):
    p = tmp_path / "in.txt"
    p.write_text("one two one three two one\n")
    rc = wordfreq.main(["--top", "2", str(p)])
    out, err = capsys.readouterr()
    assert rc == 0
    assert out == "one 3\ntwo 2\n"
    assert err == ""


def test_cli_top_zero_exits_2(capsys):
    rc = wordfreq.main(["--top", "0", "whatever.txt"])
    out, err = capsys.readouterr()
    assert rc == 2
    assert out == ""
    assert err != ""


def test_cli_top_non_integer_exits_2(capsys):
    rc = wordfreq.main(["--top", "abc", "whatever.txt"])
    out, err = capsys.readouterr()
    assert rc == 2
    assert out == ""
    assert err != ""


def test_cli_top_negative_exits_2(capsys):
    rc = wordfreq.main(["--top", "-1", "whatever.txt"])
    out, err = capsys.readouterr()
    assert rc == 2
    assert out == ""
    assert err != ""


def test_cli_without_top_still_prints_full_report(capsys, tmp_path):
    p = tmp_path / "in.txt"
    p.write_text("a b a c\n")
    rc = wordfreq.main([str(p)])
    out, err = capsys.readouterr()
    assert rc == 0
    assert out == "a 2\nb 1\nc 1\n"
    assert err == ""
