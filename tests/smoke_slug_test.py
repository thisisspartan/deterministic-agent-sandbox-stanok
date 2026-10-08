"""Tests for src/smoke_slug.py — TASK-STANOK-CC-210.

Covers every acceptance criterion of the ticket contract: basic phrase,
punctuation runs collapse, leading/trailing separators stripped, digits
preserved, empty/separator-only input -> "".
"""

from src import smoke_slug


# ---------------------------------------------------------------------------
# basic phrase
# ---------------------------------------------------------------------------

def test_basic_phrase():
    assert smoke_slug.slug("Hello World") == "hello-world"
    assert smoke_slug.slug("Quick Brown Fox") == "quick-brown-fox"
    assert smoke_slug.slug("MiXeD CaSe Input") == "mixed-case-input"
    assert smoke_slug.slug("already-a-slug") == "already-a-slug"


# ---------------------------------------------------------------------------
# punctuation runs collapse to a single "-"
# ---------------------------------------------------------------------------

def test_punctuation_runs_collapse():
    assert smoke_slug.slug("hello,,,world") == "hello-world"
    assert smoke_slug.slug("foo --!! bar") == "foo-bar"
    assert smoke_slug.slug("a...b___c") == "a-b-c"
    assert smoke_slug.slug("one  two\tthree") == "one-two-three"
    assert smoke_slug.slug("a.b!c?d/e:f") == "a-b-c-d-e-f"


# ---------------------------------------------------------------------------
# leading/trailing separators stripped
# ---------------------------------------------------------------------------

def test_leading_trailing_separators_stripped():
    assert smoke_slug.slug("  --Hello World--  ") == "hello-world"
    assert smoke_slug.slug("!!!lead") == "lead"
    assert smoke_slug.slug("trail!!!") == "trail"
    assert smoke_slug.slug("_under_scores_") == "under-scores"


# ---------------------------------------------------------------------------
# digits preserved
# ---------------------------------------------------------------------------

def test_digits_preserved():
    assert smoke_slug.slug("Top 10 Tips 2024") == "top-10-tips-2024"
    assert smoke_slug.slug("abc123def") == "abc123def"
    assert smoke_slug.slug("123") == "123"


# ---------------------------------------------------------------------------
# empty / separator-only input -> ""
# ---------------------------------------------------------------------------

def test_empty_and_separator_only():
    assert smoke_slug.slug("") == ""
    assert smoke_slug.slug("   ") == ""
    assert smoke_slug.slug("---!!!...") == ""
    assert smoke_slug.slug("___") == ""
