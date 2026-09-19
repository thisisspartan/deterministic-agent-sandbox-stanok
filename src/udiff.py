"""Unified diff generator (LCS-based, exact output format).

Stdlib only. Exposes exactly one function: diff(old, new, context=3).
"""


def _lcs_matches(old, new):
    """Return the list of (old_idx, new_idx) pairs of the LCS alignment,
    in file order (strictly increasing indices on both sides)."""
    m, n = len(old), len(new)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        oi = old[i - 1]
        row = dp[i]
        prev = dp[i - 1]
        for j in range(1, n + 1):
            if oi == new[j - 1]:
                row[j] = prev[j - 1] + 1
            else:
                row[j] = prev[j] if prev[j] >= row[j - 1] else row[j - 1]
    matches = []
    i, j = m, n
    while i > 0 and j > 0:
        if old[i - 1] == new[j - 1] and dp[i][j] == dp[i - 1][j - 1] + 1:
            matches.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    matches.reverse()
    return matches


def diff(old: list, new: list, context: int = 3) -> str:
    """Compute the unified diff of two line lists.

    Lines are compared exactly (no trailing-newline semantics). Changed
    lines are aligned by their longest common subsequence; within one
    change block all deletions are emitted before all insertions. Change
    blocks are expanded by `context` unchanged lines on each side and
    merged into one hunk when <= 2*context unchanged lines separate them.
    Returns "" when the lists are identical.
    """
    # Segments alternate between unchanged lines and change blocks:
    #   ("eq", old_idx, new_idx)
    #   ("chg", old_start, old_end, new_start, new_end)  (half-open ranges)
    segments = []
    poi = pni = -1
    for oi, ni in _lcs_matches(old, new):
        if oi > poi + 1 or ni > pni + 1:
            segments.append(("chg", poi + 1, oi, pni + 1, ni))
        segments.append(("eq", oi, ni))
        poi, pni = oi, ni
    if poi + 1 < len(old) or pni + 1 < len(new):
        segments.append(("chg", poi + 1, len(old), pni + 1, len(new)))

    block_idx = [i for i, s in enumerate(segments) if s[0] == "chg"]
    if not block_idx:
        return ""

    # Expand each change block by up to `context` unchanged lines per side
    # (clamped at file boundaries and at neighboring blocks).
    ranges = []
    for i in block_idx:
        j = i - 1
        k = 0
        while j >= 0 and segments[j][0] == "eq" and k < context:
            j -= 1
            k += 1
        left = j + 1
        j = i + 1
        k = 0
        while j < len(segments) and segments[j][0] == "eq" and k < context:
            j += 1
            k += 1
        right = j
        ranges.append([left, right])

    # Merge blocks whose ranges touch or overlap: that is exactly the case
    # where <= 2*context unchanged lines separate them.
    merged = [ranges[0]]
    for r in ranges[1:]:
        if r[0] <= merged[-1][1]:
            if r[1] > merged[-1][1]:
                merged[-1][1] = r[1]
        else:
            merged.append(r)

    out = []
    for left, right in merged:
        oc = nc = 0
        old_first = new_first = None
        body = []
        for seg in segments[left:right]:
            if seg[0] == "eq":
                oi, ni = seg[1], seg[2]
                if old_first is None:
                    old_first = oi
                if new_first is None:
                    new_first = ni
                oc += 1
                nc += 1
                body.append(" " + old[oi] + "\n")
            else:
                _, os_, oe_, ns_, ne_ = seg
                if old_first is None and os_ < oe_:
                    old_first = os_
                if new_first is None and ns_ < ne_:
                    new_first = ns_
                oc += oe_ - os_
                nc += ne_ - ns_
                for k in range(os_, oe_):
                    body.append("-" + old[k] + "\n")
                for k in range(ns_, ne_):
                    body.append("+" + new[k] + "\n")
        if oc > 0:
            os = old_first + 1
        else:
            # Hunk has no old lines at all (pure insertion with zero old
            # context): the 1-based index of the old line immediately
            # before the insertion point, or 0 if at the very start.
            # With zero old context the hunk is a single pure-insertion
            # block, so its old range start is exactly that index.
            os = segments[left][2]
        if nc > 0:
            ns = new_first + 1
        else:
            ns = segments[left][3]
        out.append("@@ -%d,%d +%d,%d @@\n" % (os, oc, ns, nc))
        out.extend(body)
    return "".join(out)
