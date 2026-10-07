"""Tests for src/smoke_rot.py — TASK-STANOK-CC-205.

Covers every vector in the ticket contract plus the deterministic
reference checks and the "inputs are never mutated" guarantee.
"""

import copy

from src import smoke_rot


# ---------------------------------------------------------------------------
# rotate_left
# ---------------------------------------------------------------------------

def test_rotate_left_vectors():
    assert smoke_rot.rotate_left([], 3) == []
    assert smoke_rot.rotate_left([1, 2, 3], 0) == [1, 2, 3]
    assert smoke_rot.rotate_left([1, 2, 3], 1) == [2, 3, 1]
    assert smoke_rot.rotate_left([1, 2, 3], 4) == [2, 3, 1]
    assert smoke_rot.rotate_left([1, 2, 3, 4], 2) == [3, 4, 1, 2]


def test_rotate_left_matches_reference():
    items = list(range(50))
    k = 17
    reference = items[17:] + items[:17]
    assert smoke_rot.rotate_left(items, k) == reference


# ---------------------------------------------------------------------------
# rotate_right
# ---------------------------------------------------------------------------

def test_rotate_right_vectors():
    assert smoke_rot.rotate_right([], 5) == []
    assert smoke_rot.rotate_right([1, 2, 3], 0) == [1, 2, 3]
    assert smoke_rot.rotate_right([1, 2, 3], 1) == [3, 1, 2]
    assert smoke_rot.rotate_right([1, 2, 3], 4) == [3, 1, 2]
    assert smoke_rot.rotate_right([1, 2, 3, 4], 2) == [3, 4, 1, 2]


def test_rotate_right_matches_reference():
    items = list(range(50))
    k = 17
    reference = items[-17:] + items[:-17]
    assert smoke_rot.rotate_right(items, k) == reference


# ---------------------------------------------------------------------------
# caesar
# ---------------------------------------------------------------------------

def test_caesar_vectors():
    assert smoke_rot.caesar("", 7) == ""
    assert smoke_rot.caesar("abc", 1) == "bcd"
    assert smoke_rot.caesar("xyz", 3) == "abc"
    assert smoke_rot.caesar("ABC", -1) == "ZAB"
    assert smoke_rot.caesar("Hello, World!", 3) == "Khoor, Zruog!"
    assert smoke_rot.caesar("aA", 26) == "aA"


def test_caesar_rot13_is_self_inverse():
    s = "The quick brown fox"
    assert smoke_rot.caesar(smoke_rot.caesar(s, 13), 13) == s


# ---------------------------------------------------------------------------
# Inputs are never mutated
# ---------------------------------------------------------------------------

def test_inputs_are_not_mutated():
    items = [1, 2, 3, 4]
    snapshot = copy.deepcopy(items)
    smoke_rot.rotate_left(items, 2)
    smoke_rot.rotate_right(items, 2)
    assert items == snapshot

    # A returned list must be a new object, not the input aliased.
    out = smoke_rot.rotate_left(items, 1)
    assert out is not items

    text = "Hello, World!"
    assert smoke_rot.caesar(text, 3) != text  # transformed
    assert text == "Hello, World!"  # original string untouched
