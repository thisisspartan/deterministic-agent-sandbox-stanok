#!/usr/bin/env python3
"""Reference tests for src/csvlite.py (ticket TASK-STANOK-PY-01).

Plain script (no pytest/unittest): exit 0 = all pass, non-zero = fail.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.csvlite import parse, render  # noqa: E402


def check(name, cond, detail=""):
    if not cond:
        print("FAIL: %s %s" % (name, detail))
        sys.exit(1)
    print("ok: %s" % name)


def main():
    # --- parse ---
    check('parse("") == []', parse("") == [])
    check('parse("a,b\\n") == [["a", "b"]]',
          parse("a,b\n") == [["a", "b"]])
    check('parse("a,b\\nc,d") == [["a", "b"], ["c", "d"]]',
          parse("a,b\nc,d") == [["a", "b"], ["c", "d"]])
    check('parse("a,b\\r\\nc,d") == [["a", "b"], ["c", "d"]]',
          parse("a,b\r\nc,d") == [["a", "b"], ["c", "d"]])
    check('parse("a\\rb") == [["a\\rb"]]',
          parse("a\rb") == [["a\rb"]])
    check('parse(\'"x,y",z\') == [["x,y", "z"]]',
          parse('"x,y",z') == [["x,y", "z"]])
    check('parse(\'"a""b",c\') == [["a\\"b", "c"]]',
          parse('"a""b",c') == [["a\"b", "c"]])
    check('parse(\'"line1\\nline2",b\') == [["line1\\nline2", "b"]]',
          parse('"line1\nline2",b') == [["line1\nline2", "b"]])
    check('parse(\'""\') == [[""]]', parse('""') == [[""]])
    check('parse(" , ") == [[" ", " "]]', parse(" , ") == [[" ", " "]])

    try:
        parse('"unclosed')
        check('parse(\'"unclosed\') raises ValueError', False,
              "(no exception raised)")
    except ValueError:
        check('parse(\'"unclosed\') raises ValueError', True)
    except Exception as e:
        check('parse(\'"unclosed\') raises ValueError', False,
              "(raised %r instead)" % (e,))

    # --- render ---
    check('render([["a", "b"]]) == "a,b"', render([["a", "b"]]) == "a,b")
    check('render([["x,y", "z"]]) == \'"x,y",z\'',
          render([["x,y", "z"]]) == '"x,y",z')
    check('render([["a\\"b"]]) == \'"a""b"\'',
          render([['a"b']]) == '"a""b"')
    check('render([["l1\\nl2"]]) == \'"l1\\nl2"\'',
          render([["l1\nl2"]]) == '"l1\nl2"')

    # --- round-trip ---
    rows = [["a", "b,c"], ['d"e', "f\ng"], ["h\r", ""]]
    check("round-trip parse(render(rows)) == rows",
          parse(render(rows)) == rows)

    print("ALL PASS")


if __name__ == "__main__":
    main()
