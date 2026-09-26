"""Pure structural helpers: list flattening and chunking.

Two pure functions, no I/O, no state:

- ``flatten(nested)`` — recursively flattens arbitrarily nested lists into a
  single flat list; empty lists and lists of empty lists -> ``[]``; the
  input list is not mutated.
- ``chunk(lst, n)`` — splits a list into consecutive chunks of length ``n``
  (the last chunk may be shorter); ``n < 1`` -> ``ValueError``; empty list
  -> ``[]``.
"""

from __future__ import annotations


def flatten(nested: list) -> list:
    """Recursively flatten ``nested`` into a single flat list.

    - elements that are lists are recursed into (arbitrary depth);
    - empty lists and lists of empty lists contribute nothing -> ``[]``;
    - the input list is not mutated; a new list is returned.
    """
    flat: list = []
    for item in nested:
        if isinstance(item, list):
            flat.extend(flatten(item))
        else:
            flat.append(item)
    return flat


def chunk(lst: list, n: int) -> list:
    """Split ``lst`` into consecutive chunks of length ``n``.

    - the last chunk may be shorter than ``n``;
    - ``n < 1`` -> ``ValueError``;
    - empty list -> ``[]``.
    """
    if n < 1:
        raise ValueError("chunk size n must be >= 1, got %r" % (n,))
    return [lst[i:i + n] for i in range(0, len(lst), n)]
