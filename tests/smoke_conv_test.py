"""Reference tests for src/smoke_conv.py (TASK-STANOK-CC-183).

Covers the ticket contract:
- to_base(n, base): non-negative int to lowercase base-2..36 string;
  ValueError for n < 0 or base outside 2..36.
- from_base(s, base): parse lowercase/uppercase digits in base 2..36;
  ValueError for empty string, invalid digit, or base outside 2..36.
- roman(n): canonical uppercase Roman numeral for 1 <= n <= 3999;
  ValueError otherwise.
- roman_value(s): parse a canonical uppercase Roman numeral; ValueError
  for empty string, characters outside MDCLXVI, or non-canonical form.
"""

import pytest

from smoke_conv import from_base, roman, roman_value, to_base


# --- to_base -----------------------------------------------------------

def test_to_base_zero():
    assert to_base(0, 2) == "0"
    assert to_base(0, 10) == "0"
    assert to_base(0, 16) == "0"
    assert to_base(0, 36) == "0"


def test_to_base_single_digit():
    for d in range(10):
        assert to_base(d, 10) == str(d)
    assert to_base(10, 16) == "a"
    assert to_base(15, 16) == "f"
    assert to_base(35, 36) == "z"


def test_to_base_powers_of_the_base():
    assert to_base(1, 2) == "1"
    assert to_base(2, 2) == "10"
    assert to_base(8, 2) == "1000"
    assert to_base(16, 16) == "10"
    assert to_base(256, 16) == "100"
    assert to_base(1000, 10) == "1000"
    assert to_base(36, 36) == "10"
    assert to_base(1296, 36) == "100"


def test_to_base_255_in_base_16():
    assert to_base(255, 16) == "ff"


def test_to_base_base36_uses_letters():
    assert to_base(1295, 36) == "zz"
    assert to_base(1000, 36) == "rs"


def test_to_base_negative_n_raises_value_error():
    with pytest.raises(ValueError):
        to_base(-1, 10)
    with pytest.raises(ValueError):
        to_base(-255, 16)


def test_to_base_base_out_of_range_raises_value_error():
    with pytest.raises(ValueError):
        to_base(10, 1)
    with pytest.raises(ValueError):
        to_base(10, 37)


# --- from_base ----------------------------------------------------------

def test_from_base_examples():
    assert from_base("ff", 16) == 255
    assert from_base("1010", 2) == 10


def test_from_base_round_trip_with_to_base():
    for base in (2, 8, 10, 16, 36):
        for n in (0, 1, 7, 42, 255, 1295, 10**6):
            assert from_base(to_base(n, base), base) == n


def test_from_base_uppercase_input_accepted():
    assert from_base("FF", 16) == 255
    assert from_base("ABC", 16) == 2748
    assert from_base("ZZ", 36) == 1295


def test_from_base_empty_string_raises_value_error():
    with pytest.raises(ValueError):
        from_base("", 10)


def test_from_base_invalid_digit_for_base_raises_value_error():
    with pytest.raises(ValueError):
        from_base("2", 2)
    with pytest.raises(ValueError):
        from_base("12", 2)
    with pytest.raises(ValueError):
        from_base("g", 16)
    with pytest.raises(ValueError):
        from_base("8", 8)


def test_from_base_base_out_of_range_raises_value_error():
    with pytest.raises(ValueError):
        from_base("10", 1)
    with pytest.raises(ValueError):
        from_base("10", 37)


# --- roman ---------------------------------------------------------------

def test_roman_ticket_examples():
    assert roman(1) == "I"
    assert roman(4) == "IV"
    assert roman(9) == "IX"
    assert roman(40) == "XL"
    assert roman(90) == "XC"
    assert roman(400) == "CD"
    assert roman(900) == "CM"
    assert roman(1994) == "MCMXCIV"
    assert roman(3999) == "MMMCMXCIX"


def test_roman_milestones():
    assert roman(10) == "X"
    assert roman(50) == "L"
    assert roman(100) == "C"
    assert roman(500) == "D"
    assert roman(1000) == "M"
    assert roman(3999) == "MMMCMXCIX"


def test_roman_out_of_range_raises_value_error():
    with pytest.raises(ValueError):
        roman(0)
    with pytest.raises(ValueError):
        roman(4000)
    with pytest.raises(ValueError):
        roman(-1)


# --- roman_value ----------------------------------------------------------

def test_roman_value_example():
    assert roman_value("MCMXCIV") == 1994


def test_roman_value_round_trip_with_roman():
    for n in (1, 4, 9, 40, 90, 400, 900, 1994, 3999):
        assert roman_value(roman(n)) == n


def test_roman_value_empty_string_raises_value_error():
    with pytest.raises(ValueError):
        roman_value("")


def test_roman_value_lowercase_raises_value_error():
    with pytest.raises(ValueError):
        roman_value("iv")
    with pytest.raises(ValueError):
        roman_value("mcmxciv")


def test_roman_value_character_outside_mdclxvi_raises_value_error():
    with pytest.raises(ValueError):
        roman_value("MA")
    with pytest.raises(ValueError):
        roman_value("1")


def test_roman_value_non_canonical_raises_value_error():
    with pytest.raises(ValueError):
        roman_value("IIII")
    with pytest.raises(ValueError):
        roman_value("VV")
    with pytest.raises(ValueError):
        roman_value("IC")
