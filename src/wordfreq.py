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


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the exit code.

    argv[0] (if present) is the input file; otherwise stdin is read.
    Exit codes: 0 success; 2 file missing/unreadable.
    """
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        path = argv[0]
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            print(f"wordfreq: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
            return 2
    else:
        text = sys.stdin.read()
    report = format_report(frequencies(tokenize(text)))
    if report:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
