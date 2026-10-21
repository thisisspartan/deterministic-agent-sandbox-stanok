"""CC-315 — tests for src/wordcount.py: the contract C1..C3, with negatives.

C1  tokenization: a token is a maximal non-empty run of [A-Za-z0-9_],
    lowercased; everything else (whitespace, punctuation, non-ASCII) is a
    separator.
C2  result: dict token -> count, insertion order = first occurrence;
    "" and "!!!" -> {}.
C3  purity: stdlib `re` only, no I/O, no state between calls, the argument
    is not mutated.

A negative test is worth as much as a positive one here: the separators are
pinned by inputs that MUST NOT produce a token, and purity is pinned by
inputs whose second result must equal the first.
"""

import inspect
import re

try:
    from src import wordcount as _wc
    from src.wordcount import count_words
except ImportError:  # bare import: src/ is on sys.path via pythonpath=src
    import wordcount as _wc
    from wordcount import count_words


# ---------------------------------------------------------------------------
# C1: tokens and separators
# ---------------------------------------------------------------------------

def test_counts_repeated_words():
    assert count_words("one two one three two one") == {
        "one": 3, "two": 2, "three": 1,
    }


def test_case_is_folded_to_lower():
    assert count_words("Foo FOO foo") == {"foo": 3}
    assert count_words("MiXeD CaSe MIXED case") == {"mixed": 2, "case": 2}


def test_underscore_and_digits_are_part_of_a_token():
    # Case is folded; `_` is NOT folded away — it is part of the token, so
    # "a_1" and "a1" are two different tokens (C1).
    assert count_words("a_1 A_1") == {"a_1": 2}
    assert count_words("a_1 A1") == {"a_1": 1, "a1": 1}
    assert count_words("_private_ 42 ___ 007") == {
        "_private_": 1, "42": 1, "___": 1, "007": 1,
    }


def test_whitespace_and_newlines_are_separators():
    assert count_words("a b\nc\td\r\ne a") == {"a": 2, "b": 1, "c": 1, "d": 1, "e": 1}


def test_punctuation_splits_tokens_and_is_not_counted():
    # "hello, world! hello-world hello_world" ->
    #   hello | world | hello | world | hello_world
    assert count_words("hello, world! hello-world hello_world") == {
        "hello": 2, "world": 2, "hello_world": 1,
    }
    assert count_words("don't") == {"don": 1, "t": 1}


def test_non_ascii_is_a_separator_not_a_token_character():
    # C1 pins the ASCII class: é, Cyrillic and CJK are separators.
    assert count_words("café naïve") == {"caf": 1, "na": 1, "ve": 1}
    assert count_words("привет мир") == {}
    assert count_words("日本語 token 中文") == {"token": 1}


def test_every_non_token_character_alone_yields_no_tokens():
    assert count_words("") == {}
    assert count_words("!!!") == {}
    assert count_words("   \t\n ,.;: ()[]{}#@$%^&*-=+|\\/~`\"'<>") == {}
    assert count_words("—–‘’“”…") == {}


# ---------------------------------------------------------------------------
# C2: the result shape — counts and insertion order
# ---------------------------------------------------------------------------

def test_insertion_order_is_the_first_occurrence():
    result = count_words("b a c a b d")
    assert list(result) == ["b", "a", "c", "d"]
    assert result == {"a": 2, "b": 2, "c": 1, "d": 1}  # counts, order above


def test_lowercased_token_is_inserted_at_its_first_occurrence():
    result = count_words("Bar foo BAR Foo")
    assert list(result) == ["bar", "foo"]
    assert result == {"bar": 2, "foo": 2}


def test_result_is_a_plain_dict_of_str_to_int():
    result = count_words("x1 x1 y")
    assert type(result) is dict
    assert all(isinstance(k, str) and type(v) is int for k, v in result.items())


# ---------------------------------------------------------------------------
# C3: purity — determinism, no mutation, no state between calls
# ---------------------------------------------------------------------------

def test_two_identical_calls_are_identical():
    text = "x y x z y x"
    first = count_words(text)
    second = count_words(text)
    assert first == second
    assert list(first) == list(second)  # same order, not just same content


def test_the_argument_string_is_not_mutated():
    text = "Hello hello"
    before = text
    count_words(text)
    assert text == before


def test_the_returned_dict_is_not_shared_with_a_later_call():
    text = "hello hello"
    result = count_words(text)
    result["hello"] += 1
    result["injected"] = 1
    assert count_words(text) == {"hello": 2}


def test_a_call_is_independent_of_the_previous_one():
    assert count_words("a b a") == {"a": 2, "b": 1}
    assert count_words("c") == {"c": 1}
    assert count_words("a b a") == {"a": 2, "b": 1}


def test_no_output_is_produced(capsys):
    count_words("quiet words quiet")
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_module_holds_no_public_state_and_no_public_name_but_count_words():
    # C3: no state between calls — no public mutable container; C1: one
    # public function.
    public = {name: value for name, value in vars(_wc).items()
              if not name.startswith("_")}
    assert {n for n, v in public.items() if isinstance(v, (dict, list, set, bytearray))} == set()
    assert {n for n, v in public.items() if inspect.isfunction(v)} == {"count_words"}


def test_only_stdlib_re_is_imported_and_there_is_no_io():
    source = inspect.getsource(_wc)
    imported = set()
    for match in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_.]*)",
                             source, re.MULTILINE):
        imported.add(match.group(1).split(".")[0])
    assert imported <= {"re", "__future__"}
    for forbidden in ("open(", "sys.stdin", "sys.stdout", "sys.stderr",
                      "input(", "print(", "random", "time.", "os."):
        assert forbidden not in source
