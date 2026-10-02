"""Reference tests for src/smoke_b32.py (TASK-STANOK-CC-187).

Covers the ticket contract:
- b32_encode(data): RFC 4648 base32, alphabet A-Z2-7, `=` padding to a
  multiple of 8 characters; the seven ticket vectors (b"" -> "", b"f" ->
  "MY======", b"fo" -> "MZXQ====", b"foo" -> "MZXW6===", b"foob" ->
  "MZXW6YQ=", b"fooba" -> "MZXW6YTB", b"foobar" -> "MZXW6YTBOI======");
  output is always uppercase and either empty or a multiple of 8 chars;
  trailing-padding counts for input lengths 1..6 are 6, 4, 3, 1, 0, 6.
- b32_decode(s): the ticket vectors; case-insensitive input; round-trip
  b32_decode(b32_encode(x)) == x for input lengths 0..20 (all residue
  classes mod 3).
- ValueError on: a character outside the alphabet plus `=` (digit `1`);
  a `=` not in the final padding position(s); a total length that is not
  0 and not a multiple of 8; a trailing-padding count not in
  {0, 1, 3, 4, 6} (including an all-padding block).
"""

import pytest

from smoke_b32 import b32_decode, b32_encode


# ---------------------------------------------------------------- b32_encode

def test_encode_empty():
    assert b32_encode(b"") == ""


def test_encode_f():
    assert b32_encode(b"f") == "MY======"


def test_encode_fo():
    assert b32_encode(b"fo") == "MZXQ===="


def test_encode_foo():
    assert b32_encode(b"foo") == "MZXW6==="


def test_encode_foob():
    assert b32_encode(b"foob") == "MZXW6YQ="


def test_encode_fooba():
    assert b32_encode(b"fooba") == "MZXW6YTB"


def test_encode_foobar():
    assert b32_encode(b"foobar") == "MZXW6YTBOI======"


def test_encode_output_uppercase_and_multiple_of_8():
    for n in range(0, 21):
        data = bytes((i * 37 + 11) % 256 for i in range(n))
        out = b32_encode(data)
        assert isinstance(out, str)
        assert out == out.upper()
        assert out == "" or len(out) % 8 == 0


def test_encode_trailing_padding_counts():
    # Input lengths 1..6 -> trailing `=` counts 6, 4, 3, 1, 0, 6.
    expected = {1: 6, 2: 4, 3: 3, 4: 1, 5: 0, 6: 6}
    for n, pad in expected.items():
        data = bytes((i * 53 + 7) % 256 for i in range(n))
        out = b32_encode(data)
        assert out.endswith("=" * pad)
        assert not out.endswith("=" * (pad + 1))


# ---------------------------------------------------------------- b32_decode

def test_decode_fooba():
    assert b32_decode("MZXW6YTB") == b"fooba"


def test_decode_foobar():
    assert b32_decode("MZXW6YTBOI======") == b"foobar"


def test_decode_lowercase_same_as_uppercase():
    assert b32_decode("mzxw6ytb") == b"fooba"
    assert b32_decode("mzxw6ytboi======") == b"foobar"
    assert b32_decode("mzxw6ytb") == b32_decode("MZXW6YTB")


def test_decode_empty():
    assert b32_decode("") == b""


def test_roundtrip_lengths_0_to_20():
    # All residue classes mod 3 are covered by lengths 0..20.
    for n in range(0, 21):
        data = bytes((i * 97 + 31) % 256 for i in range(n))
        assert b32_decode(b32_encode(data)) == data


# ------------------------------------------------------------- ValueError

def test_decode_digit_1_not_in_alphabet():
    with pytest.raises(ValueError):
        b32_decode("M1XW6YTB")


def test_decode_equals_in_middle():
    with pytest.raises(ValueError):
        b32_decode("M=ZXW6YT")


def test_decode_length_3_not_multiple_of_8():
    with pytest.raises(ValueError):
        b32_decode("MY=")


def test_decode_length_9_not_multiple_of_8():
    with pytest.raises(ValueError):
        b32_decode("MZXW6YTBO")


def test_decode_invalid_padding_count_2():
    # 8 chars with 2 trailing `=`: padding count 2 is not in {0,1,3,4,6}.
    with pytest.raises(ValueError):
        b32_decode("MZXW6Y==")


def test_decode_all_padding_block():
    # 8 `=`: trailing-padding count 8 is not in {0,1,3,4,6}.
    with pytest.raises(ValueError):
        b32_decode("========")


# ------------------------------------------------------------------- purity

def test_encode_does_not_mutate_input():
    data = b"mutation check"
    before = bytes(data)
    b32_encode(data)
    assert data == before
