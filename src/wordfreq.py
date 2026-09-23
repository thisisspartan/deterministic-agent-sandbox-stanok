"""wordfreq — small deterministic word-frequency CLI (Python 3.11 stdlib).

Reads text from a file argument or stdin, tokenizes it into words
(maximal runs of [a-z0-9] after lowercasing), and prints one
``<word> <count>`` line per distinct word, sorted by count descending
then word ascending.
"""

import re
import sys

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Return lowercased word tokens (maximal [a-z0-9] runs), in order."""
    return _WORD_RE.findall(text.lower())


def frequencies(tokens: list[str]) -> dict[str, int]:
    """Count word occurrences: word -> count."""
    freq: dict[str, int] = {}
    for token in tokens:
        freq[token] = freq.get(token, 0) + 1
    return freq


def format_report(freq: dict[str, int]) -> str:
    """Render the report: sorted `<word> <count>` lines joined by \\n,
    no trailing newline; empty dict -> ""."""
    if not freq:
        return ""
    items = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return "\n".join(f"{word} {count}" for word, count in items)


def top_n(freq: dict[str, int], n: int) -> list[tuple[str, int]]:
    """Return the top ``n`` entries in report order (count descending,
    then word ascending — the same order ``format_report`` uses).
    ``n <= 0`` -> []; ``n >= len(freq)`` -> all entries; empty dict -> [].
    """
    if n <= 0:
        return []
    items = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:n]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the exit code.

    Usage: wordfreq [--top N] [file]. The optional input file is read
    from the remaining argument; otherwise stdin is read. With
    ``--top N`` only the top N report lines are printed.
    Exit codes: 0 success; 2 file missing/unreadable, or ``--top`` given
    a non-integer or non-positive argument.
    """
    if argv is None:
        argv = sys.argv[1:]
    top: int | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--top":
            if i + 1 >= len(argv):
                print("wordfreq: --top requires an integer argument", file=sys.stderr)
                return 2
            value = argv[i + 1]
            try:
                n = int(value)
            except ValueError:
                print(f"wordfreq: --top expects an integer, got {value!r}", file=sys.stderr)
                return 2
            if n < 1:
                print(f"wordfreq: --top must be a positive integer, got {n}", file=sys.stderr)
                return 2
            top = n
            i += 2
        else:
            rest.append(arg)
            i += 1
    if rest:
        path = rest[0]
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            print(f"wordfreq: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
            return 2
    else:
        text = sys.stdin.read()
    freq = frequencies(tokenize(text))
    if top is not None:
        freq = dict(top_n(freq, top))
    report = format_report(freq)
    if report:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
