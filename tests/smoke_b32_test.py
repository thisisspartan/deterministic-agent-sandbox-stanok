"""Reference tests for src/smoke_b32.py (TASK-STANOK-CC-187).

Covers the ticket contract:
- b32_encode(data): RFC 4648 base32, alphabet A-Z2-7, '=' padding to a
  multiple of 8 characters; the seven ticket vectors; output always
  uppercase and either empty or a multiple of 8 chars; trailing-padding
  counts for input lengths 1..6 are 6, 4, 3, 1, 0, 6.
- b32_decode(s): the three ticket vectors; case-insensitive input;
  round-trip b32_decode(b32_encode(x)) == x for input lengths 0..20
  (all residue classes mod 3).
- ValueError on: a character outside the alphabet plus '=' (digit '1');
  a '=' not in the final padding position(s); a total length that is not
  0 and not a multiple of 8; a trailing-padding count not in
  {0, 1, 3, 4, 6}; an all-padding block.
- purity: inputs are never mutated.
"""

import pytest

from smoke_b32 import b32_decode, b32_encode


# --------------------------------------------------------------- b32_encode

def test_encode_empty():
    assert b32_encode(b"") == ""


def test_encode_ticket_vectors():
    assert b32_encode(b"f") == "MY======"
    assert b32_encode(b"fo") == "MZXQ===="
    assert b32_encode(b"foo") == "MZXW6==="
    assert b32_encode(b"foob") == "MZXW6YQ="
    assert b32_encode(b"fooba") == "MZXW6YTB"
    assert b32_encode(b"foobar") == "MZXW6YTBOI======"


def test_encode_output_uppercase_and_multiple_of_8():
    alphabet = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    for n in range(0, 21):
        data = bytes((i * 37 + 11) % 256 for i in range(n))
        out = b32_encode(data)
        assert isinstance(out, str)
        assert out == "" or len(out) % 8 == 0
        for ch in out:
            assert ch in alphabet or ch == "="


def test_encode_trailing_padding_counts_for_lengths_1_to_6():
    # n bytes -> ceil(n*8/5) chars, padded to a multiple of 8:
    # lengths 1..5 give 8 chars, length 6 gives 16 chars.
    expected = {1: (6, 8), 2: (4, 8), 3: (3, 8), 4: (1, 8), 5: (0, 8), 6: (6, 16)}
    for n, (pad, total) in expected.items():
        data = bytes((i * 37 + 11) % 256 for i in range(n))
        out = b32_encode(data)
        assert out.endswith("=" * pad)
        assert not out.endswith("=" * (pad + 1))
        assert len(out) == total


# ---------------------------------------------------------------- b32_decode

def test_decode_ticket_vectors():
    assert b32_decode("MZXW6YTB") == b"fooba"
    # 16 chars total: 10 alphabet chars + 6 '=' (matches b32_encode(b"foobar"))
    assert b32_decode("MZXW6YTBOI" + "=" * 6) == b"foobar"
    assert b32_decode("mzxw6ytb") == b"fooba"


def test_decode_empty():
    assert b32_decode("") == b""


def test_decode_lowercase_same_as_uppercase():
    for n in range(0, 21):
        data = bytes((i * 37 + 11) % 256 for i in range(n))
        up = b32_encode(data)
        assert b32_decode(up.lower()) == b32_decode(up) == data


def test_roundtrip_lengths_0_to_20():
    # lengths 0..20 cover every residue class mod 3 (and mod 8)
    for n in range(0, 21):
        data = bytes((i * 37 + 11) % 256 for i in range(n))
        assert b32_decode(b32_encode(data)) == data


# ------------------------------------------------------------- ValueError

def test_decode_valueerror_digit_one_not_in_alphabet():
    with pytest.raises(ValueError):
        b32_decode("M1XW6YTB")


def test_decode_valueerror_eq_in_middle():
    with pytest.raises(ValueError):
        b32_decode("M=ZXW6YT")


def test_decode_valueerror_length_not_multiple_of_8():
    with pytest.raises(ValueError):
        b32_decode("MY=")          # 3 chars
    with pytest.raises(ValueError):
        b32_decode("MZXW6YTBO")    # 9 chars


def test_decode_valueerror_invalid_padding_count():
    # 8 chars with 2 trailing '=' — 2 is not in {0, 1, 3, 4, 6}
    with pytest.raises(ValueError):
        b32_decode("MZXW6Y==")


def test_decode_valueerror_all_padding_block():
    with pytest.raises(ValueError):
        b32_decode("========")


def test_decode_valueerror_other_out_of_alphabet_chars():
    for bad in ("MZXW6YTB1", "MZXW6YTB-", "MZXW6YTB ", "MZXW6YTB8", "MZXW6YTB0"):
        with pytest.raises(ValueError):
            b32_decode(bad)


# -------------------------------------------------------------------- purity

def test_inputs_never_mutated():
    data = b"mutation check"
    before = bytes(data)
    out = b32_encode(data)
    assert data == before
    s = "MZXW6YTBOI======"
    before_s = str(s)
    b32_decode(s)
    assert s == before_s
    # encode output is a fresh string, decode output a fresh bytes object
    assert b32_decode(out) is not data
