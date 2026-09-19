# `src/udiff.py` — unified diff generator

`diff(old: list[str], new: list[str], context: int = 3) -> str` computes the
unified diff of two lists of lines (lines compared exactly, stdlib only).
Lines are aligned by their longest common subsequence: LCS lines are
unchanged context, remaining old lines are deletions, remaining new lines are
insertions, and within one change block all deletions are emitted before all
insertions. Change blocks are expanded by `context` unchanged lines on each
side (clamped at file boundaries) and merged into a single hunk when at most
`2 * context` unchanged lines separate them. Output is one
`@@ -<os>,<oc> +<ns>,<nc> @@` header per hunk (counts always printed, even 0;
start index of a pure-insertion/pure-deletion hunk is the 1-based index of
the line immediately before the change point, or 0 at the file start)
followed by body lines prefixed with ` `/`-`/`+`, every line including the
last ending in `\n`. If the inputs are identical the function returns `""`.
The module is import-safe (no side effects) and exposes exactly `diff`.
