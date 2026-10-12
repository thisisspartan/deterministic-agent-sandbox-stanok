"""Reference tests for TASK-STANOK-CC-254: src/text_stats.py — a deterministic
text-stats utility (counting, top-N words, file/stdin input, CLI).

The CLI output format is pinned here and in docs/text_stats.md (same input ->
byte-identical output):

    lines <L>
    words <W>
    chars <C>
    top <M>
    <count> <word>        (M = min(n, number of distinct words) lines)

CLI contract: `python -m src.text_stats [file] [-n N]`, default N=10; invalid
arguments -> argparse standard behavior (exit code 2, message on stderr).
"""

import pathlib
import subprocess
import sys

import pytest

import text_stats

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def run_cli(*args, stdin_text=None):
    """Run the CLI as a subprocess from the repo root (module path src.text_stats)."""
    return subprocess.run(
        [sys.executable, "-m", "src.text_stats", *args],
        cwd=str(REPO_ROOT),
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# --- counting ------------------------------------------------------------------


def test_empty_input_all_counts_are_zero_and_top_is_empty():
    assert text_stats.count_stats("") == (0, 0, 0)
    assert text_stats.top_words("", 5) == []


def test_counts_lines_words_characters_basic():
    text = "hello world\nfoo\n"
    # lines: splitlines semantics -> ["hello world", "foo"]; words: split() -> 3;
    # chars: every character including both newlines.
    assert text_stats.count_stats(text) == (2, 3, 16)


def test_trailing_newline_does_not_add_an_empty_line():
    assert text_stats.count_stats("one\n") == (1, 1, 4)
    assert text_stats.count_stats("one") == (1, 1, 3)
    # blank lines ARE lines; only the trailing newline is not one.
    assert text_stats.count_stats("a\n\n\n") == (3, 1, 4)


def test_unicode_and_cyrillic_words_counted_case_preserved():
    text = "Привет мир привет\n"
    assert text_stats.count_stats(text) == (1, 3, 18)
    # No case folding: "Привет" and "привет" are distinct words.
    assert text_stats.top_words(text, 3) == [
        ("Привет", 1),
        ("мир", 1),
        ("привет", 1),
    ]
    # Non-ASCII Latin and symbols are ordinary characters/words too.
    text2 = "naïve café Ω-λ x\n"  # 5+1+4+1+3+1+1 chars + newline = 17
    assert text_stats.count_stats(text2) == (1, 4, 17)
    assert text_stats.top_words(text2, 1) == [("naïve", 1)]


def test_crlf_line_count_matches_splitlines_and_cr_never_in_words():
    text = "a b\r\nc\r\n"  # 2+2+1+2+1 chars = 8
    # splitlines() treats \r\n as one line break -> 2 lines; \r counts as a
    # character; words contain no \r.
    assert text_stats.count_stats(text) == (2, 3, 8)
    assert text_stats.top_words(text, 3) == [("a", 1), ("b", 1), ("c", 1)]
    # A lone \r is also a line break per splitlines(), and never part of a word.
    assert text_stats.count_stats("x\ry") == (2, 2, 3)


# --- top-N words ---------------------------------------------------------------


def test_top_words_sorted_by_count_descending_and_truncated_to_n():
    text = "a a a b b c"
    assert text_stats.top_words(text, 2) == [("a", 3), ("b", 2)]
    # n larger than the number of distinct words -> all of them, sorted.
    assert text_stats.top_words(text, 10) == [("a", 3), ("b", 2), ("c", 1)]
    assert text_stats.top_words(text, 1) == [("a", 3)]


def test_top_words_ties_broken_by_first_occurrence():
    # All counts equal -> the order of first occurrence in the text wins.
    text = "banana apple cherry banana apple cherry"
    assert text_stats.top_words(text, 2) == [("banana", 2), ("apple", 2)]
    assert text_stats.top_words(text, 3) == [
        ("banana", 2),
        ("apple", 2),
        ("cherry", 2),
    ]
    # Mixed: higher count first, ties within equal counts by first occurrence.
    text2 = "x y x y z"
    assert text_stats.top_words(text2, 3) == [("x", 2), ("y", 2), ("z", 1)]


def test_top_words_n_below_one_returns_empty():
    text = "a a b"
    assert text_stats.top_words(text, 0) == []
    assert text_stats.top_words(text, -1) == []
    assert text_stats.top_words(text, -100) == []


# --- input source ---------------------------------------------------------------


def test_read_text_path_reads_file_bytes_verbatim(tmp_path):
    p = tmp_path / "input.txt"
    p.write_bytes("Привет\r\nмир".encode("utf-8"))
    # Raw read: no newline translation, no decoding surprises.
    assert text_stats.read_text(str(p)) == "Привет\r\nмир"


# --- CLI ------------------------------------------------------------------------


def test_cli_output_format_pinned_file_and_stdin_and_default_n(tmp_path):
    text = "foo bar foo baz\n"
    expected = "lines 1\nwords 4\nchars 16\ntop 2\n2 foo\n1 bar\n"

    p = tmp_path / "in.txt"
    p.write_text(text, encoding="utf-8")
    proc = run_cli(str(p), "-n", "2")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == expected

    # Same text via stdin (no file argument) -> byte-identical output.
    proc = run_cli("-n", "2", stdin_text=text)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == expected

    # Default N=10: all distinct words listed, count-desc, ties by first occurrence.
    proc = run_cli(str(p))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        "lines 1\nwords 4\nchars 16\ntop 3\n2 foo\n1 bar\n1 baz\n"
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--bogus"],            # unknown flag
        ["-n", "abc"],          # -n is not an integer
        ["-n"],                 # -n without a value
        ["a.txt", "b.txt"],     # more than one positional file
    ],
)
def test_cli_invalid_arguments_exit_2_with_message_on_stderr(tmp_path, args):
    p = tmp_path / "a.txt"
    p.write_text("x\n", encoding="utf-8")
    argv = [a if a != "a.txt" else str(p) for a in args]
    proc = run_cli(*argv)
    assert proc.returncode == 2
    assert proc.stderr.strip() != ""


# --- larger input (~10 KB synthetic) ----------------------------------------------

WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]


def _synthetic_text():
    """Deterministic ~10 KB text: 500 lines, line i holds (i % 6) + 1 words."""
    lines = [" ".join(WORDS[: (i % 6) + 1]) for i in range(500)]
    return "\n".join(lines) + "\n"


def test_large_synthetic_input_counts_and_top_verified():
    text = _synthetic_text()
    # Expected values computed by construction, not by the implementation:
    # 500 lines; words per line k=1..6 appear 84,84,83,83,83,83 times ->
    # 84*(1+2) + 83*(3+4+5+6) = 1746 words; line lengths 5,10,16,22,30,35 ->
    # 84*(5+10) + 83*(16+22+30+35) + 500 newlines = 10309 characters.
    assert len(text) >= 10_000  # the ticket's "~10 KB synthetic text"
    assert text_stats.count_stats(text) == (500, 1746, 10309)
    # word j appears in every line with k >= j: 500, 416, 332, 249, 166, 83.
    assert text_stats.top_words(text, 3) == [
        ("alpha", 500),
        ("beta", 416),
        ("gamma", 332),
    ]
    assert text_stats.top_words(text, 6) == [
        ("alpha", 500),
        ("beta", 416),
        ("gamma", 332),
        ("delta", 249),
        ("epsilon", 166),
        ("zeta", 83),
    ]
