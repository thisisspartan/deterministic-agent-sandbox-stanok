"""Unified diff generator (LCS-based, stdlib only).

Exposes exactly one function: diff(old, new, context=3) -> str.
The exact output string is the contract; see docs/udiff.md.
"""


def diff(old: list[str], new: list[str], context: int = 3) -> str:
    """Return the unified diff of two line lists.

    Lines are compared exactly (the inputs are already split lines).
    Returns "" when the two lists are identical.
    """
    n, m = len(old), len(new)

    # dp[i][j] = length of the LCS of old[i:] and new[j:].
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row = dp[i]
        nxt = dp[i + 1]
        for j in range(m - 1, -1, -1):
            if old[i] == new[j]:
                row[j] = nxt[j + 1] + 1
            else:
                a = nxt[j]
                b = row[j + 1]
                row[j] = a if a >= b else b

    # Walk the LCS alignment, producing an event stream:
    # ("eq", line) | ("del", old line) | ("ins", new line).
    events = []
    i = j = 0
    while i < n or j < m:
        if i < n and j < m and old[i] == new[j]:
            events.append(("eq", old[i]))
            i += 1
            j += 1
        elif i == n:
            events.append(("ins", new[j]))
            j += 1
        elif j == m:
            events.append(("del", old[i]))
            i += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            events.append(("del", old[i]))
            i += 1
        else:
            events.append(("ins", new[j]))
            j += 1

    # Split the stream into segments, which strictly alternate:
    #   ("eq", count)
    #   ("chg", old_first, del_count, new_first, ins_count, dels, ins)
    # where old_first/new_first are the 0-based indices of the first
    # deleted/inserted line. A change block is a maximal run of
    # deletions/insertions between two consecutive LCS matches.
    segs = []
    i = j = 0
    k = 0
    while k < len(events):
        if events[k][0] == "eq":
            count = 0
            while k < len(events) and events[k][0] == "eq":
                k += 1
                i += 1
                j += 1
                count += 1
            segs.append(("eq", count))
        else:
            old_first, new_first = i, j
            dels, ins = [], []
            while k < len(events) and events[k][0] != "eq":
                op, line = events[k]
                if op == "del":
                    dels.append(line)
                    i += 1
                else:
                    ins.append(line)
                    j += 1
                k += 1
            segs.append(("chg", old_first, len(dels), new_first, len(ins),
                        dels, ins))

    # Indices (into segs) of the change blocks.
    chg_idx = [idx for idx, s in enumerate(segs) if s[0] == "chg"]
    if not chg_idx:
        return ""

    # For each change block, how many unchanged lines sit immediately
    # before / after it (equal runs are 1:1, so the count is the same
    # in both files).
    eq_before = [0] * len(segs)
    eq_after = [0] * len(segs)
    for idx in chg_idx:
        eq_before[idx] = segs[idx - 1][1] if idx > 0 else 0
        eq_after[idx] = segs[idx + 1][1] if idx + 1 < len(segs) else 0

    # Group change blocks into hunks: two blocks merge when the
    # unchanged run between them is <= 2 * context lines long.
    groups = []
    cur = []
    for idx in chg_idx:
        if cur and segs[idx - 1][1] > 2 * context:
            groups.append(cur)
            cur = []
        cur.append(idx)
    groups.append(cur)

    # Emit the hunks.
    out = []
    for idxs in groups:
        first, last = segs[idxs[0]], segs[idxs[-1]]
        # The equal runs are 1:1, so the context clamping is identical
        # on the old and new side.
        old_start = first[1] - min(context, eq_before[idxs[0]])
        old_end = last[1] + last[2] + min(context, eq_after[idxs[-1]])
        new_start = first[3] - min(context, eq_before[idxs[0]])
        new_end = last[3] + last[4] + min(context, eq_after[idxs[-1]])
        old_count = old_end - old_start
        new_count = new_end - new_start
        # For a hunk with no old (new) lines at all, the start index is
        # the 0-based count of lines before the change point.
        os_ = old_start + 1 if old_count > 0 else old_start
        ns_ = new_start + 1 if new_count > 0 else new_start
        out.append("@@ -%d,%d +%d,%d @@\n" % (os_, old_count, ns_, new_count))

        pos = old_start
        for bi in idxs:
            _, b_old_first, b_d, _, b_s, b_dels, b_ins = segs[bi]
            for idx in range(pos, b_old_first):
                out.append(" " + old[idx] + "\n")
            for line in b_dels:
                out.append("-" + line + "\n")
            for line in b_ins:
                out.append("+" + line + "\n")
            pos = b_old_first + b_d
        for idx in range(pos, old_end):
            out.append(" " + old[idx] + "\n")

    return "".join(out)
