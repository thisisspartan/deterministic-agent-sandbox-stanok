#!/usr/bin/env python3
"""Test contract for src/csvlite.py (see docs/csvlite.md).

Plain Python script: run directly with ``python3 tests/csvlite_test.py``.
Exit code 0 = all checks pass, non-zero = failure. No pytest/unittest
imports; the single ``test_*`` function exists only so the project's
pytest-based run.sh entrypoint can collect the same checks.

Import-safe: no side effects, no blocking calls on import.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.csvlite import parse, render  # noqa: E402


def check_all():
    # --- parse: empty input ---
    assert parse("") == [], "parse('') must return []"

    # --- parse: trailing record separator yields no empty final record ---
    assert parse("a,b\n") == [["a", "b"]], "trailing \\n must not create a record"

    # --- parse: multiple records separated by \\n ---
    assert parse("a,b\nc,d") == [["a", "b"], ["c", "d"]]

    # --- parse: CRLF record separator ---
    assert parse("a,b\r\nc,d") == [["a", "b"], ["c", "d"]], "CRLF must separate records"

    # --- parse: bare \\r is an ordinary character inside a field ---
    assert parse("a\rb") == [["a\rb"]], "bare \\r must be literal field content"

    # --- parse: comma inside a quoted field ---
    assert parse('"x,y",z') == [["x,y", "z"]]

    # --- parse: doubled quote is an escaped literal quote ---
    assert parse('"a""b",c') == [["a\"b", "c"]]

    # --- parse: newline inside a quoted field is literal content ---
    assert parse('"line1\nline2",b') == [["line1\nline2", "b"]]

    # --- parse: empty quoted field ---
    assert parse('""') == [[""]]

    # --- parse: no trimming; spaces are significant and preserved ---
    assert parse(" , ") == [[" ", " "]]

    # --- parse: unterminated quoted field is malformed -> ValueError ---
    try:
        parse('"unclosed')
    except ValueError:
        pass
    else:
        raise AssertionError("parse('\"unclosed') must raise ValueError")

    # --- render: plain fields, joined by ',' and '\\n', no trailing newline ---
    assert render([["a", "b"]]) == "a,b"

    # --- render: quote only when needed (comma triggers quoting) ---
    assert render([["x,y", "z"]]) == '"x,y",z'

    # --- render: embedded quotes are doubled ---
    assert render([['a"b']]) == '"a""b"'

    # --- render: embedded newline triggers quoting ---
    assert render([["l1\nl2"]]) == '"l1\nl2"'

    # --- round-trip: parse(render(rows)) == rows ---
    rows = [["a", "b,c"], ['d"e', "f\ng"], ["h\r", ""]]
    assert parse(render(rows)) == rows, "round-trip must be lossless"


def test_csvlite_contract():
    """Collected by run.sh's pytest runner; runs the same plain-script checks."""
    check_all()


if __name__ == "__main__":
    check_all()
