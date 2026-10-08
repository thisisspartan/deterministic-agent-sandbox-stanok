"""smoke_text — pure text utilities (CC-209).

Two pure functions, no imports, no randomness. Inputs are never mutated.
"""


def is_palindrome(text):
    """Case-insensitive palindrome check over letters and digits.

    Only alphanumeric characters are considered; every other character is
    ignored. Case is folded. An empty string is a palindrome.
    """
    cleaned = [ch.lower() for ch in text if ch.isalnum()]
    return cleaned == cleaned[::-1]


def caesar(text, shift):
    """Caesar cipher over ASCII letters, wrapping within each case.

    Each ASCII letter is shifted by ``shift`` positions within its own case
    (a-z, A-Z); non-letters pass through unchanged. ``shift`` may be negative
    or larger than 26. The input string is not mutated.
    """
    result = []
    for ch in text:
        if "a" <= ch <= "z":
            base = ord("a")
        elif "A" <= ch <= "Z":
            base = ord("A")
        else:
            result.append(ch)
            continue
        result.append(chr((ord(ch) - base + shift) % 26 + base))
    return "".join(result)
