"""Deterministic text-stats utility (TASK-STANOK-CC-254).

Counting semantics (pinned in tests/text_stats_test.py and docs/text_stats.md):
- characters: every character including newlines -> len(text);
- lines: str.splitlines() semantics (a trailing newline does NOT add an empty
  line; a lone \\r is a line break too);
- words: maximal runs of non-whitespace characters -> str.split() semantics.

top_words(text, n) returns [(word, count), ...] sorted by count descending;
ties are broken by first occurrence in the text (dict insertion order + a
stable sort). n < 1 yields []. No randomness, no locale or time dependence:
input is decoded as UTF-8 explicitly, never through the locale.

CLI: `python -m src.text_stats [file] [-n N]` (default N=10). path=None reads
all of stdin (raw bytes, UTF-8); a path is read verbatim (no newline
translation). Invalid arguments -> argparse standard behavior (exit 2, message
on stderr). Output format (deterministic, byte-identical for the same input):

    lines <L>
    words <W>
    chars <C>
    top <M>
    <count> <word>        (M = min(n, number of distinct words) lines)
"""

import argparse
import sys


def count_stats(text):
    """Return (lines, words, characters) for `text`.

    lines: len(text.splitlines()); words: len(text.split());
    characters: len(text) — every character, newlines included.
    """
    return len(text.splitlines()), len(text.split()), len(text)


def top_words(text, n):
    """Top-N words as [(word, count), ...]: count descending, ties by first
    occurrence in the text. n < 1 -> []. Case is preserved (no folding)."""
    if n < 1:
        return []
    counts = {}
    for word in text.split():
        counts[word] = counts.get(word, 0) + 1
    # dict preserves first-occurrence order; sort is stable and keyed only on
    # the count, so equal counts keep that order.
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    return ranked[:n]


def read_text(path=None):
    """Read the input text: `path=None` reads all of stdin, else the file.

    Both paths are raw: stdin bytes are decoded as UTF-8 explicitly (never via
    the locale), files are opened with newline="" so no newline translation
    happens — the text is the input verbatim.
    """
    if path is None:
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def format_report(stats, top):
    """Render the pinned output: counts, then `top <M>` and one line per entry."""
    lines, words, chars = stats
    out = [f"lines {lines}", f"words {words}", f"chars {chars}", f"top {len(top)}"]
    out.extend(f"{count} {word}" for word, count in top)
    return "\n".join(out) + "\n"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="text_stats",
        description="Count lines/words/characters and list the top-N words.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="input file (default: read all of stdin)",
    )
    parser.add_argument(
        "-n",
        type=int,
        default=10,
        metavar="N",
        help="number of top words to print (default: 10; n < 1 prints none)",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    text = read_text(args.file)
    stats = count_stats(text)
    top = top_words(text, args.n)
    sys.stdout.write(format_report(stats, top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
