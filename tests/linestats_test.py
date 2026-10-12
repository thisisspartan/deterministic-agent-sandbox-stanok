"""Acceptance tests for src/linestats.py (TASK-STANOK-CC-246).

Contract under test:
- line_count(text) -> int: number of lines; a trailing newline does NOT add an
  empty line; "" -> 0.
- blank_line_count(text) -> int: lines that are empty or whitespace-only.
- longest_line(text) -> str: the longest line by character count; ties resolve
  to the FIRST occurrence; "" -> "".
"""

from src.linestats import blank_line_count, line_count, longest_line


# --- line_count -------------------------------------------------------------

def test_line_count_empty_text():
    assert line_count("") == 0


def test_line_count_single_line_without_newline():
    assert line_count("hello") == 1


def test_line_count_single_line_with_trailing_newline():
    # The trailing newline terminates the line, it does not add an empty one.
    assert line_count("hello\n") == 1


def test_line_count_multiple_lines():
    assert line_count("one\ntwo\nthree") == 3
    assert line_count("one\ntwo\nthree\n") == 3


def test_line_count_lone_newline_is_one_empty_line():
    # "\n" is a single (empty) line terminated by a newline.
    assert line_count("\n") == 1
    assert line_count("\n\n") == 2


def test_line_count_interior_empty_lines_are_counted():
    assert line_count("a\n\nb") == 3
    assert line_count("\n\na") == 3


def test_line_count_crlf_and_lf_agree():
    # Line terminators are normalized: CRLF and LF give the same counts.
    assert line_count("a\r\nb\r\nc") == 3
    assert line_count("a\r\nb\r\nc\r\n") == 3
    assert line_count("a\r\nb\r\nc") == line_count("a\nb\nc")
    assert line_count("a\r\n\r\nb") == line_count("a\n\nb") == 3


def test_line_count_multiline_block():
    text = "\r\n".join(["header", "", "body line", "  ", "footer"])
    assert line_count(text) == 5


# --- blank_line_count -------------------------------------------------------

def test_blank_line_count_empty_text():
    assert blank_line_count("") == 0


def test_blank_line_count_no_blank_lines():
    assert blank_line_count("a\nb\nc") == 0
    assert blank_line_count("a\nb\nc\n") == 0


def test_blank_line_count_empty_lines():
    assert blank_line_count("\n") == 1
    assert blank_line_count("a\n\nb") == 1
    assert blank_line_count("a\n\n\nb") == 2
    assert blank_line_count("\n\n") == 2


def test_blank_line_count_whitespace_only_lines_are_blank():
    # Spaces, tabs and their combinations count as blank lines.
    assert blank_line_count("a\n   \nb") == 1
    assert blank_line_count("a\n\t\nb") == 1
    assert blank_line_count("a\n \t \nb") == 1
    assert blank_line_count("   ") == 1
    assert blank_line_count("  \n\t\n") == 2


def test_blank_line_count_trailing_whitespace_line_is_blank():
    # "a\n   " is a second line holding only spaces -> blank.
    assert blank_line_count("a\n   ") == 1
    # "a\n" has no second line at all -> nothing blank.
    assert blank_line_count("a\n") == 0


def test_blank_line_count_crlf_matches_lf():
    text_crlf = "a\r\n\r\nb\r\n  \r\n"
    text_lf = "a\n\nb\n  \n"
    assert blank_line_count(text_crlf) == 2
    assert blank_line_count(text_crlf) == blank_line_count(text_lf)


def test_blank_line_count_non_blank_line_with_inner_whitespace():
    # Whitespace inside a line does not make it blank.
    assert blank_line_count("a b\n\tc\t") == 0


# --- longest_line -----------------------------------------------------------

def test_longest_line_empty_text():
    assert longest_line("") == ""


def test_longest_line_single_line():
    assert longest_line("hello") == "hello"
    assert longest_line("hello\n") == "hello"


def test_longest_line_exact_value():
    text = "short\nthe longest line here\nmid"
    assert longest_line(text) == "the longest line here"


def test_longest_line_ignores_line_terminators():
    # The returned line never carries its own newline / CRLF.
    assert longest_line("a\r\nbbbb\r\nc") == "bbbb"
    assert "\n" not in longest_line("a\nbbbb\nc")
    assert "\r" not in longest_line("a\r\nbbbb\r\nc")


def test_longest_line_tie_returns_first_occurrence():
    text = "aaaa\nbbbb\ncccc"
    assert longest_line(text) == "aaaa"
    assert longest_line("x\nabcd\nABCD") == "abcd"
    assert longest_line("short\nsame length\ntoo") == "same length"


def test_longest_line_tie_with_crlf_and_lf_mix():
    assert longest_line("abcd\r\nefgh\nijkl") == "abcd"


def test_longest_line_all_lines_equal_returns_first():
    assert longest_line("a\nb\nc") == "a"


def test_longest_line_blank_text_of_only_newlines():
    # Every line is empty; the longest is the empty string.
    assert longest_line("\n\n\n") == ""


def test_longest_line_whitespace_only_lines_can_be_longest():
    assert longest_line("a\n    \nbb") == "    "


def test_longest_line_counts_unicode_by_characters():
    # One character is one character regardless of its width in bytes:
    # "café" is 4 characters (5 bytes in UTF-8), so it beats "abc" (3).
    assert longest_line("abc\ncafé") == "café"
    assert longest_line("abc\nпривет\nhi") == "привет"
    assert longest_line("abcd\néclair") == "éclair"
    # Equal character counts tie even when the byte counts differ -> first wins.
    assert longest_line("abcd\ncéfé") == "abcd"
    # An emoji is one character.
    assert longest_line("abcdefg\n😀😀") == "abcdefg"
    assert longest_line("😀😀😀\nab") == "😀😀😀"


def test_longest_line_returns_a_str():
    assert isinstance(longest_line("abc\ndefgh"), str)
