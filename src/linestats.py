"""linestats — line statistics over a plain string (TASK-STANOK-CC-246).

Contract (stdlib only, no I/O):
- line_count(text) returns the number of lines in the string; a trailing
  newline terminates the last line and does not add an empty one; "" gives 0.
- blank_line_count(text) returns the number of lines that are empty or hold
  nothing but whitespace.
- longest_line(text) returns the longest line by character count; ties resolve
  to the FIRST occurrence; "" gives "".

All three share one line-splitting rule: universal newlines (LF, CRLF, CR)
terminate a line and are never part of it, so LF and CRLF input behave
identically.
"""


def _lines(text: str) -> list[str]:
    """Split `text` into its lines.

    Line terminators (LF, CRLF, CR) are stripped and never appear in a result;
    a trailing terminator does not produce a trailing empty line, so "" gives
    [] and "a\n" gives ["a"].
    """
    return text.splitlines()


def line_count(text: str) -> int:
    """Return the number of lines in `text` ("" gives 0; a trailing newline
    does not add an empty line)."""
    return len(_lines(text))


def blank_line_count(text: str) -> int:
    """Return the number of blank lines in `text` — lines that are empty or
    contain nothing but whitespace."""
    return sum(1 for line in _lines(text) if not line.strip())


def longest_line(text: str) -> str:
    """Return the longest line of `text` measured in characters.

    On a tie the FIRST occurrence wins (the comparison is strict, so a later
    line of equal length never replaces the current best). "" gives "".
    """
    best = ""
    for line in _lines(text):
        if len(line) > len(best):
            best = line
    return best
