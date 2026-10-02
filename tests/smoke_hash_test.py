"""Reference tests for src/smoke_hash.py (TASK-STANOK-CC-185).

Covers the ticket contract:
- fnv1a_32(data): FNV-1a 32-bit; offset basis 2166136261, prime 16777619;
  vectors b"" -> 2166136261, b"a" -> 0xE40C292C, b"foobar" -> 0xBF9CF968;
  result always < 2**32.
- djb2(data): DJB2 32-bit; h = 5381, h = (h*33 + b) % 2**32;
  vectors b"" -> 5381, b"a" -> 177670; result always < 2**32.
- crc8(data, poly=0x07): classic CRC-8 (no reflection, init 0, no final
  XOR); vectors b"" -> 0, b"123456789" -> 0xF4; honours the poly argument;
  result always < 256; empty input is 0 for any polynomial.
- width invariants: for a batch of random-ish byte strings, all three
  digests stay within their bit width.
- purity: input bytes are never mutated.
"""

import pytest

from smoke_hash import crc8, djb2, fnv1a_32


# ---------------------------------------------------------------- fnv1a_32

def test_fnv1a_32_empty_is_offset_basis():
    assert fnv1a_32(b"") == 2166136261


def test_fnv1a_32_single_byte_a():
    # FNV-1a 32 of b"a": ((0x811C9DC5 ^ 0x61) * 0x01000193) % 2**32.
    assert fnv1a_32(b"a") == 0xE40C292C


def test_fnv1a_32_foobar():
    assert fnv1a_32(b"foobar") == 0xBF9CF968


def test_fnv1a_32_longer_input_deterministic_and_32bit():
    data = b"hello world"
    h1 = fnv1a_32(data)
    h2 = fnv1a_32(data)
    assert h1 == h2
    assert isinstance(h1, int)
    assert 0 <= h1 < 2**32


def test_fnv1a_32_result_always_within_32_bits():
    for data in (b"", b"\x00", b"\xff", b"a", b"foobar", b"hello world",
                 bytes(range(256))):
        h = fnv1a_32(data)
        assert isinstance(h, int)
        assert 0 <= h < 2**32


# --------------------------------------------------------------------- djb2

def test_djb2_empty_is_5381():
    assert djb2(b"") == 5381


def test_djb2_single_byte_a():
    assert djb2(b"a") == 177670


def test_djb2_longer_input_deterministic_and_32bit():
    data = b"the quick brown fox jumps over the lazy dog"
    h1 = djb2(data)
    h2 = djb2(data)
    assert h1 == h2
    assert isinstance(h1, int)
    assert 0 <= h1 < 2**32


def test_djb2_result_always_within_32_bits():
    for data in (b"", b"\x00", b"\xff", b"a", b"foobar", b"hello world",
                 bytes(range(256))):
        h = djb2(data)
        assert isinstance(h, int)
        assert 0 <= h < 2**32


# --------------------------------------------------------------------- crc8

def test_crc8_empty_is_zero():
    assert crc8(b"") == 0


def test_crc8_check_value_default_poly():
    assert crc8(b"123456789") == 0xF4


def test_crc8_custom_poly_differs_from_default():
    data = b"123456789"
    assert crc8(data, poly=0x31) != crc8(data, poly=0x07)


def test_crc8_result_always_within_8_bits():
    for data in (b"", b"\x00", b"\xff", b"a", b"123456789",
                 bytes(range(256))):
        h = crc8(data)
        assert isinstance(h, int)
        assert 0 <= h < 256


def test_crc8_empty_is_zero_for_any_poly():
    for poly in (0x00, 0x07, 0x31, 0x9B, 0xFF):
        assert crc8(b"", poly=poly) == 0


# ------------------------------------------------------- width invariants

def test_width_invariants_randomish_batch():
    # Deterministic pseudo-random batch (no RNG state, no imports needed).
    batch = []
    seed = 0x12345678
    for i in range(64):
        seed = (seed * 1103515245 + 12345) % (2**31)
        length = seed % 40
        batch.append(bytes((seed >> (j % 24)) & 0xFF for j in range(length)))
    for data in batch:
        assert 0 <= fnv1a_32(data) < 2**32
        assert 0 <= djb2(data) < 2**32
        assert 0 <= crc8(data) < 256


# ------------------------------------------------------------------- purity

def test_input_bytes_never_mutated():
    data = b"mutation check"
    for fn in (fnv1a_32, djb2):
        before = bytes(data)
        fn(data)
        assert data == before
    before = bytes(data)
    crc8(data)
    crc8(data, poly=0x31)
    assert data == before


def test_functions_return_int():
    assert isinstance(fnv1a_32(b"x"), int)
    assert isinstance(djb2(b"x"), int)
    assert isinstance(crc8(b"x"), int)
