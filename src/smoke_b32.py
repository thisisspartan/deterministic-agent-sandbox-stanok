"""Small pure RFC 4648 base32 codec.

Two pure functions, no I/O, no state, stdlib only (no ``base64`` module):

- ``b32_encode(data: bytes) -> str`` — encode bytes to base32 using the
  RFC 4648 alphabet ``A-Z2-7`` (A=0 ... Z=25, 2=26 ... 7=31), padded with
  ``=`` to a multiple of 8 characters. ``b32_encode(b"") == ""``.
- ``b32_decode(s: str) -> bytes`` — decode a padded base32 string back to
  bytes. Input is case-insensitive. Raises ``ValueError`` on any
  character outside the alphabet plus ``=``, on a ``=`` that is not in
  the final padding position(s), on a total length that is not 0 and not
  a multiple of 8, and on a trailing-padding count not in
  ``{0, 1, 3, 4, 6}``.

Both functions are pure: inputs are never mutated, and
``b32_decode(b32_encode(x)) == x`` for every ``x: bytes``.
"""

from __future__ import annotations

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_DECODE_TABLE = {c: i for i, c in enumerate(_ALPHABET)}
_VALID_PAD = (0, 1, 3, 4, 6)


def b32_encode(data: bytes) -> str:
    """Encode ``data`` to RFC 4648 base32 with ``=`` padding.

    The output is always uppercase and either empty or a multiple of 8
    characters. ``b32_encode(b"") == ""``,
    ``b32_encode(b"foobar") == "MZXW6YTBOI======"``.
    """
    out = []
    buf = 0
    bits = 0
    for b in data:
        buf = (buf << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_ALPHABET[(buf >> bits) & 31])
    if bits:
        out.append(_ALPHABET[(buf << (5 - bits)) & 31])
    s = "".join(out)
    return s + "=" * ((-len(s)) % 8)


def b32_decode(s: str) -> bytes:
    """Decode a padded base32 string ``s`` back to bytes.

    Case-insensitive. Raises ``ValueError`` on:
    - any character outside the alphabet plus ``=``;
    - a ``=`` that is not in the final padding position(s);
    - a total length that is not 0 and not a multiple of 8;
    - a trailing-padding count not in ``{0, 1, 3, 4, 6}``.

    ``b32_decode("MZXW6YTB") == b"fooba"``,
    ``b32_decode("MZXW6YTBOI======") == b"foobar"``.
    """
    if not s:
        return b""
    if len(s) % 8 != 0:
        raise ValueError(
            f"base32 length {len(s)} is not 0 and not a multiple of 8"
        )
    pad = 0
    for ch in reversed(s):
        if ch == "=":
            pad += 1
        else:
            break
    if pad not in _VALID_PAD:
        raise ValueError(
            f"invalid trailing padding count {pad} (must be 0, 1, 3, 4 or 6)"
        )
    body = s[: len(s) - pad]
    buf = 0
    bits = 0
    out = bytearray()
    for ch in body:
        v = _DECODE_TABLE.get(ch.upper())
        if v is None:
            raise ValueError(f"invalid base32 character {ch!r}")
        buf = (buf << 5) | v
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((buf >> bits) & 0xFF)
    return bytes(out)
