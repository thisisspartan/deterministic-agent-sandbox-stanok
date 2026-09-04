#!/usr/bin/env python3
"""Analysis of the native run transcript: output_tokens, thinking, M1/M2.

Usage: analyze-evidence.py <transcript.jsonl>

The transcript is the original ~/.claude/projects/<slug>/<session-id>.jsonl
(not probe-*.jsonl: there output_tokens is zeroed out by a serialization artifact).
Responses are deduplicated by message.id.

M1 — Read/Glob/Grep touching live files (launch.log, probe-*.jsonl,
     evidence.jsonl, launcher.stdout.log) — a self-reference loop.
M2 — identity episodes in thinking ("my own session/log" etc.).
"""
import json
import re
import sys


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0
    k = (len(sorted_vals) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def main():
    path = sys.argv[1]
    responses = {}  # message.id -> usage
    thinking_chars = 0
    thinking_blocks = []  # (message.id, text)
    tool_hits = []  # M1
    ROUTE = re.compile(
        r"launch\.log|probe-[0-9a-f-]+\.jsonl|evidence\.jsonl|launcher\.stdout\.log",
        re.I,
    )
    n_lines = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            n_lines += 1
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "assistant":
                continue
            msg = d.get("message") or {}
            mid = msg.get("id")
            usage = msg.get("usage") or {}
            if mid and usage:
                if mid not in responses:
                    responses[mid] = usage
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "thinking":
                    t = b.get("thinking", "")
                    thinking_chars += len(t)
                    thinking_blocks.append((mid, t))
                elif b.get("type") == "tool_use":
                    name = b.get("name", "")
                    inp = b.get("input") or {}
                    blob = json.dumps(inp, ensure_ascii=False)
                    if name in ("Read", "Glob", "Grep") and ROUTE.search(blob):
                        tool_hits.append((name, blob[:300]))

    outs = sorted(u.get("output_tokens", 0) for u in responses.values())
    over8 = [v for v in outs if v > 8192]
    over12 = [v for v in outs if v > 12288]

    # M2: identity episodes in thinking
    IDENTITY = re.compile(
        r"my own (session|log|transcript|thinking|probe|evidence)|"
        r"own session['\"]?s? (log|transcript)|"
        r"this (is|launch\.log is|file is) (my|our) own|"
        r"reading my own|whoa",
        re.I,
    )
    identity = []
    for mid, t in thinking_blocks:
        for m in IDENTITY.finditer(t):
            s = max(0, m.start() - 150)
            identity.append((mid, t[s:m.end() + 150].replace("\n", " ")))
            break  # one block = one episode

    result = {
        "transcript": path,
        "lines": n_lines,
        "responses": len(outs),
        "output_tokens": {
            "max": outs[-1] if outs else 0,
            "p50": pct(outs, 50),
            "p90": pct(outs, 90),
            "p95": pct(outs, 95),
            "p99": pct(outs, 99),
            "over_8192": len(over8),
            "over_8192_pct": round(100 * len(over8) / len(outs), 1) if outs else 0,
            "over_12288": len(over12),
            "over_12288_pct": round(100 * len(over12) / len(outs), 1) if outs else 0,
            "top5": outs[-5:],
        },
        "thinking_chars_total": thinking_chars,
        "thinking_blocks": len(thinking_blocks),
        "M1_tool_hits_on_live_files": tool_hits,
        "M1_count": len(tool_hits),
        "M2_identity_episodes": len(identity),
        "M2_samples": identity[:5],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
