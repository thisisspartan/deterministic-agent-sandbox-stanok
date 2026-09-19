#!/usr/bin/env python3
"""Reference tests for src/udiff.py (ticket TASK-STANOK-PY-03).

Plain script (no pytest/unittest): exit 0 = all pass, non-zero = fail.
All assertions are on the EXACT output string.
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


# Identical inputs -> no diff.
check("identical", diff(["a", "b", "c"], ["a", "b", "c"]), "")
check("identical-single", diff(["a"], ["a"]), "")
check("identical-both-empty", diff([], []), "")

# Single-line replace in the middle.
check(
    "middle-replace",
    diff(["a", "b", "c"], ["a", "X", "c"]),
    "@@ -1,3 +1,3 @@\n a\n-b\n+X\n c\n",
)

# Deletion in the middle.
check(
    "middle-delete",
    diff(["a", "b", "c"], ["a", "c"]),
    "@@ -1,3 +1,2 @@\n a\n-b\n c\n",
)

# Insertion at the very start.
check(
    "head-insert",
    diff(["b", "c"], ["a", "b", "c"]),
    "@@ -1,2 +1,3 @@\n+a\n b\n c\n",
)

# Insertion between two unchanged lines.
check(
    "insert-between",
    diff(["a", "b"], ["a", "X", "b"]),
    "@@ -1,2 +1,3 @@\n a\n+X\n b\n",
)

# Trailing replace: deletions all before insertions.
check(
    "tail-replace",
    diff(["a", "b", "c"], ["a", "X", "Y"]),
    "@@ -1,3 +1,3 @@\n a\n-b\n-c\n+X\n+Y\n",
)

# Two change blocks within 2*context unchanged lines -> one merged hunk.
check(
    "merged-hunk",
    diff(["a", "b", "c", "d", "e"], ["a", "X", "c", "d", "Y"]),
    "@@ -1,5 +1,5 @@\n a\n-b\n+X\n c\n d\n-e\n+Y\n",
)

# Two change blocks further apart -> two separate hunks (context=2).
check(
    "two-hunks",
    diff(
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        ["a", "X", "c", "d", "e", "f", "g", "h", "Y", "j"],
        context=2,
    ),
    "@@ -1,4 +1,4 @@\n a\n-b\n+X\n c\n d\n"
    "@@ -7,4 +7,4 @@\n g\n h\n-i\n+Y\n j\n",
)

# Empty old file: pure insertion, -0,0 header.
check("empty-old", diff([], ["a", "b"]), "@@ -0,0 +1,2 @@\n+a\n+b\n")

# Empty new file: pure deletion, +0,0 header.
check("empty-new", diff(["a", "b"], []), "@@ -1,2 +0,0 @@\n-a\n-b\n")

# Full replacement of a single line (empty LCS).
check("full-replace", diff(["a"], ["b"]), "@@ -1,1 +1,1 @@\n-a\n+b\n")

# Pure insertion at the start with context=0: os points at the old line
# immediately before the insertion point (0 here, insertion at very start).
check(
    "pure-insert-context0",
    diff(["a", "b"], ["X", "a", "b"], context=0),
    "@@ -0,0 +1,1 @@\n+X\n",
)

print("ALL TESTS PASSED")
