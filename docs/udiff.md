# src/udiff.py

`diff(old: list[str], new: list[str], context: int = 3) -> str` computes the
unified diff of two lists of lines (stdlib only, no dependencies, import-safe).
The lists are aligned by their longest common subsequence (LCS): LCS lines are
emitted as context (` ` prefix), old lines outside the LCS as deletions (`-`),
and new lines outside the LCS as insertions (`+`); within each change block all
deletions are emitted before all insertions. Each change block is expanded by
`context` unchanged lines on each side (clamped at file boundaries), and
neighbouring change blocks merge into one hunk when the unchanged run between
them is `<= 2 * context` lines long. Each hunk starts with a header
`@@ -<os>,<oc> +<ns>,<nc> @@` where `<os>`/`<ns>` are the 1-based positions of
the first old/new line in the hunk (or `0` when the hunk has no old/new lines
and the change point is at file start) and `<oc>`/`<nc>` are the old/new line
counts, always printed even when 0 or 1; every output line, including the last,
ends with `\n`, hunks appear in file order with no blank line between them, and
the function returns `""` when the two lists are identical.
