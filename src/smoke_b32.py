"""Small pure RFC 4648 base32 codec.

Two pure functions, no I/O, no state, stdlib only (no ``base64`` module):

- ``b32_encode(data: bytes) -> str`` — encode bytes to base32 using the
  RFC 4648 alphabet ``A-Z2-7`` (A=0 ... Z=25, 2=26 ... 7=31), padded with
  ``=`` to a multiple of 8 characters. ``b32_encode(b"") == ""``.
- ``b32_decode(s: str) -> bytes`` — decode a padded base32 string back to
  bytes. Case-insensitive (accepts lowercase input). Raises ``ValueError``
  on any character outside the alphabet plus ``=``, on a ``=`` that is not
  in the final padding position(s), on a total length that is not 0 and not
  a multiple of 8, and on a trailing-padding count not in {0, 1, 3, 4, 6}.

Both functions are pure: inputs are never mutated, no global state.
``b32_decode(b32_encode(x)) == x`` for every ``x: bytes``.
"""

from __future__ import annotations

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_DECODE_TABLE = {ch: i for i, ch in enumerate(_ALPHABET)}
_VALID_PAD = (0, 1, 3, 4, 6)


def b32_encode(data: bytes) -> str:
    """Encode ``data`` to RFC 4648 base32 with ``=`` padding.

    The output is always uppercase and either empty or a multiple of 8
    characters. Valid trailing-padding counts are 0, 1, 3, 4, or 6
    (input lengths 1..6 give 6, 4, 3, 1, 0, 6 respectively).

    ``b32_encode(b"") == ""``, ``b32_encode(b"f") == "MY======="``,
    ``b32_encode(b"fo") == "MZXQ===="``, ``b32_encode(b"foo") == "MZXW6==="``,
    ``b32_encode(b"foob") == "MZXW6YQ="``, ``b32_encode(b"fooba") == "MZXW6YTB"``,
    ``b32_encode(b"foobar") == "MZXW6YTBOI======="``.
    """
    out = []
    for i in range(0, len(data), 5):
        chunk = data[i:i + 5]
        n = len(chunk)
        buf = int.from_bytes(chunk, "big")
        chars = (n * 8 + 4) // 5          # ceil(n*8 / 5)
        buf <<= 5 * chars - n * 8        # left-align the n*8 data bits
        for j in range(chars):
            out.append(_ALPHABET[(buf >> (5 * (chars - 1 - j))) & 0x1F])
    s = "".join(out)
    return s + "=" * ((-len(s)) % 8)


def b32_decode(s: str) -> bytes:
    """Decode a padded base32 string ``s`` back to bytes.

    Accepts uppercase and lowercase input (case-insensitive). Raises
    ``ValueError`` on:

    - any character outside the alphabet plus ``=``;
    - a ``=`` that is not in the final padding position(s);
    - a total length that is not 0 and not a multiple of 8;
    - a trailing-padding count not in {0, 1, 3, 4, 6}.

    ``b32_decode("MZXW6YTB") == b"fooba"``,
    ``b32_decode("MZXW6YTBOI=======") == b"foobar"``,
    ``b32_decode("mzxw6ytb") == b"fooba"``.
    """
    if not s:
        return b""
    if len(s) % 8 != 0:
        raise ValueError(
            f"base32 input length {len(s)} is not a multiple of 8")
    # Trailing padding: the run of '=' at the end.
    pad = 0
    for ch in reversed(s):
        if ch == "=":
            pad += 1
        else:
            break
    if pad not in _VALID_PAD:
        raise ValueError(
            f"invalid trailing padding count {pad} "
            f"(must be one of {', '.join(map(str, _VALID_PAD))})")
    # Everything before the padding must be alphabet; a '=' in the middle
    # is rejected here because '=' is not in the decode table.
    body = s[:len(s) - pad]
    for ch in body:
        up = ch.upper()
        if up not in _DECODE_TABLE:
            raise ValueError(f"invalid base32 character {ch!r}")
    out = bytearray()
    for i in range(0, len(s), 8):
        block = s[i:i + 8]
        p = 8 - len(block.rstrip("="))   # padding in this block (0 except last)
        val = 0
        for ch in block:
            up = ch.upper()
            val = (val << 5) | _DECODE_TABLE.get(up, 0)  # '=' contributes 0
        data_bits = 5 * (8 - p)
        data = val >> (5 * p)            # drop the zero padding bits
        n_bytes = data_bits // 8
        leftover = data_bits - 8 * n_bytes
        out += (data >> leftover).to_bytes(n_bytes, "big")
    return bytes(out)
