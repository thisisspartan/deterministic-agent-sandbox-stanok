"""smoke_rot — pure rotation / Caesar-cipher utilities (CC-205).

Three pure functions, no imports, no randomness. Inputs are never mutated;
every result is a freshly built list or string.
"""


def rotate_left(items, k):
    """Move the first ``k`` elements to the end.

    ``k`` is normalized with ``k % len(items)`` (so ``k`` may exceed the
    length); an empty list yields an empty list. The input is not mutated.
    """
    n = len(items)
    if n == 0:
        return []
    k %= n
    if k == 0:
        return list(items)
    return items[k:] + items[:k]


def rotate_right(items, k):
    """Move the last ``k`` elements to the front.

    ``k`` is normalized with ``k % len(items)``; an empty list yields an
    empty list. The input is not mutated.
    """
    n = len(items)
    if n == 0:
        return []
    k %= n
    if k == 0:
        return list(items)
    return items[-k:] + items[:-k]


def caesar(text, k):
    """Shift each ASCII letter by ``k`` positions, wrapping within its case.

    Lowercase stays in a-z, uppercase in A-Z; non-letters are unchanged.
    ``k`` may be negative or larger than 26. The input string is immutable
    and is returned unchanged when no letter is affected.
    """
    result = []
    for ch in text:
        if "a" <= ch <= "z":
            result.append(chr((ord(ch) - ord("a") + k) % 26 + ord("a")))
        elif "A" <= ch <= "Z":
            result.append(chr((ord(ch) - ord("A") + k) % 26 + ord("A")))
        else:
            result.append(ch)
    return "".join(result)
