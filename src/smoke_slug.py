"""smoke_slug — URL slug normalization (CC-210).

One pure function, no imports, no randomness. Inputs are never mutated.
"""


def slug(text):
    """Normalize text to a URL slug.

    Alphanumeric characters are lowercased and kept; every run of
    non-alphanumeric characters becomes a single ``-``. Leading and trailing
    separators are stripped (runs at the edges produce no ``-``). A text with
    no alphanumeric characters yields ``""``.
    """
    words = []
    current = []
    for ch in text:
        if ch.isalnum():
            current.append(ch.lower())
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return "-".join(words)
