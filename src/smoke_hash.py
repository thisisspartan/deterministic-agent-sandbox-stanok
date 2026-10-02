"""Small pure hash utilities.

Three pure functions, no I/O, no state, stdlib only. All take ``bytes``
input (never mutated) and return a non-negative ``int`` masked to the
hash width:

- ``fnv1a_32(data)`` — FNV-1a, 32-bit. Offset basis ``2166136261``
  (``0x811C9DC5``), prime ``16777619`` (``0x01000193``).
- ``djb2(data)`` — DJB2, 32-bit. ``h = 5381``; per byte
  ``h = (h * 33 + b) % 2**32``.
- ``crc8(data, poly=0x07)`` — classic CRC-8 (no reflection, init ``0``,
  no final XOR); honours the ``poly`` argument.
"""

from __future__ import annotations

_FNV1A_32_OFFSET = 2166136261  # 0x811C9DC5
_FNV1A_32_PRIME = 16777619     # 0x01000193
_MASK32 = 2**32 - 1


def fnv1a_32(data: bytes) -> int:
    """FNV-1a 32-bit digest of ``data``.

    For each byte ``b`` in order: ``h = ((h ^ b) * 16777619) % 2**32``,
    starting from the offset basis ``2166136261``. The result is always
    a non-negative int ``< 2**32``.

    ``fnv1a_32(b"") == 2166136261``, ``fnv1a_32(b"a") == 0xE40C292C``,
    ``fnv1a_32(b"foobar") == 0xBF9CF968``.
    """
    h = _FNV1A_32_OFFSET
    for b in data:
        h = ((h ^ b) * _FNV1A_32_PRIME) & _MASK32
    return h


def djb2(data: bytes) -> int:
    """DJB2 32-bit digest of ``data``.

    ``h = 5381``; for each byte ``b`` in order:
    ``h = (h * 33 + b) % 2**32``. The result is always a non-negative
    int ``< 2**32``.

    ``djb2(b"") == 5381``, ``djb2(b"a") == 177670``.
    """
    h = 5381
    for b in data:
        h = (h * 33 + b) & _MASK32
    return h


def crc8(data: bytes, poly: int = 0x07) -> int:
    """Classic CRC-8 digest of ``data`` (no reflection, init 0, no final XOR).

    For each byte ``b``: ``crc ^= b``, then 8 times
    ``crc = ((crc << 1) ^ (poly if crc & 0x80 else 0)) & 0xFF``.
    The ``poly`` argument selects the polynomial (default ``0x07``).
    The result is always a non-negative int ``< 256``.

    ``crc8(b"") == 0``, ``crc8(b"123456789") == 0xF4``.
    """
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ (poly if crc & 0x80 else 0)) & 0xFF
    return crc
