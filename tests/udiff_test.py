#!/usr/bin/env python3
"""Reference tests for src/udiff.py (ticket TASK-STANOK-PY-03).

Plain script (no pytest/unittest): exit 0 = all pass, non-zero = fail.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.udiff import diff  # noqa: E402


def check(name, actual, expected):
    if actual != expected:
        print("FAIL: %s" % name)
        print("  expected: %r" % expected)
        print("  actual:   %r" % actual)
        sys.exit(1)
    print("ok: %s" % name)


def main():
    # --- no changes: empty string ---
    check("identical lists -> ''", diff(["a", "b", "c"], ["a", "b", "c"]), "")
    check("single identical line -> ''", diff(["a"], ["a"]), "")

    # --- single-line change with context ---
    check("replace one line",
          diff(["a", "b", "c"], ["a", "X", "c"]),
          "@@ -1,3 +1,3 @@\n a\n-b\n+X\n c\n")

    # --- pure deletion ---
    check("delete one line",
          diff(["a", "b", "c"], ["a", "c"]),
          "@@ -1,3 +1,2 @@\n a\n-b\n c\n")

    # --- pure insertion at the start ---
    check("insert at start",
          diff(["b", "c"], ["a", "b", "c"]),
          "@@ -1,2 +1,3 @@\n+a\n b\n c\n")

    # --- pure insertion in the middle ---
    check("insert between lines",
          diff(["a", "b"], ["a", "X", "b"]),
          "@@ -1,2 +1,3 @@\n a\n+X\n b\n")

    # --- deletions emitted before insertions inside one block ---
    check("replace tail (deletions before insertions)",
          diff(["a", "b", "c"], ["a", "X", "Y"]),
          "@@ -1,3 +1,3 @@\n a\n-b\n-c\n+X\n+Y\n")

    # --- hunk merging (context=3: gap of 2 unchanged lines <= 2*3) ---
    check("merged hunk (context=3)",
          diff(["a", "b", "c", "d", "e"], ["a", "X", "c", "d", "Y"]),
          "@@ -1,5 +1,5 @@\n a\n-b\n+X\n c\n d\n-e\n+Y\n")

    # --- two separate hunks (context=2: gap of 6 unchanged lines > 2*2) ---
    check("two separate hunks (context=2)",
          diff(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
               ["a", "X", "c", "d", "e", "f", "g", "h", "Y", "j"],
               context=2),
          "@@ -1,4 +1,4 @@\n a\n-b\n+X\n c\n d\n"
          "@@ -7,4 +7,4 @@\n g\n h\n-i\n+Y\n j\n")

    # --- empty inputs: 0,0 headers ---
    check("empty old (pure insertion at start)",
          diff([], ["a", "b"]),
          "@@ -0,0 +1,2 @@\n+a\n+b\n")

    check("empty new (pure deletion)",
          diff(["a", "b"], []),
          "@@ -1,2 +0,0 @@\n-a\n-b\n")

    print("ALL PASS")


if __name__ == "__main__":
    main()
