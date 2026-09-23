"""Contract tests for src/wordfreq.py (CC-112: word-frequency CLI).

Covers the module API: tokenize, frequencies, format_report, and the
main() CLI entry point (file arg; missing file -> 2).
"""

import os
import tempfile

import wordfreq  # src is on sys.path via pythonpath=src in run.sh


# --- tokenize ----------------------------------------------------------------

def test_tokenize_lowercases():
    assert wordfreq.tokenize("Hello WORLD hello") == ["hello", "world", "hello"]


def test_tokenize_drops_punctuation_and_whitespace():
    assert wordfreq.tokenize("well, ok? ok — ok") == ["well", "ok", "ok", "ok"]
    assert wordfreq.tokenize("a\tb\nc") == ["a", "b", "c"]


def test_tokenize_keeps_digits():
    assert wordfreq.tokenize("abc123 456") == ["abc123", "456"]
    assert wordfreq.tokenize("a1b") == ["a1b"]


def test_tokenize_drops_non_ascii_separators():
    # Non-ASCII chars are separators; the ASCII runs around them survive.
    assert wordfreq.tokenize("caf\u00e9") == ["caf"]
    assert wordfreq.tokenize("\u00e9a\u00e9") == ["a"]
    assert wordfreq.tokenize("\u4f60\u597d") == []  # pure non-ASCII -> no words


def test_tokenize_empty_string():
    assert wordfreq.tokenize("") == []


def test_tokenize_apostrophe_is_separator():
    assert wordfreq.tokenize("don't stop") == ["don", "t", "stop"]


# --- frequencies -------------------------------------------------------------

def test_frequencies_counts():
    assert wordfreq.frequencies(["a", "b", "a", "c", "a"]) == {"a": 3, "b": 1, "c": 1}


def test_frequencies_empty():
    assert wordfreq.frequencies([]) == {}


# --- format_report -----------------------------------------------------------

def test_format_report_sort_count_desc_word_asc():
    freq = {"a": 2, "b": 2, "c": 1, "ab": 3}
    assert wordfreq.format_report(freq) == "ab 3\na 2\nb 2\nc 1"


def test_format_report_exact_line_format():
    freq = {"word": 1}
    assert wordfreq.format_report(freq) == "word 1"


def test_format_report_single_space_no_trailing():
    report = wordfreq.format_report({"x": 5, "y": 1})
    lines = report.split("\n")
    assert lines == ["x 5", "y 1"]
    for line in lines:
        assert line.count(" ") == 1, f"exactly one space expected in {line!r}"
        parts = line.split(" ")
        assert len(parts) == 2
        assert parts[1].isdigit()


def test_format_report_empty_dict():
    assert wordfreq.format_report({}) == ""


# --- main --------------------------------------------------------------------

def test_main_reads_from_file():
    data = "One two one Three two\n"
    fd, path = tempfile.mkstemp(prefix="wordfreq_", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        assert wordfreq.main([path]) == 0
    finally:
        os.unlink(path)


def test_main_missing_file_returns_2():
    path = os.path.join(tempfile.gettempdir(), "wordfreq_nonexistent_%d.txt" % os.getpid())
    assert not os.path.exists(path)
    assert wordfreq.main([path]) == 2


def test_main_stdin_empty():
    # No file arg -> read from stdin; stdin is /dev/null under run.sh,
    # empty input -> nothing printed, exit 0. We only check the return code
    # here with a temporarily redirected stdin.
    old_stdin = None
    try:
        devnull = open(os.devnull, "r")
        old_stdin = __import__("sys").stdin
        __import__("sys").stdin = devnull
        assert wordfreq.main([]) == 0
    finally:
        if old_stdin is not None:
            __import__("sys").stdin = old_stdin
