"""aggregate — read-only aggregator over published evidence (G2, 2026-10-14).

Aggregates ALREADY-PUBLISHED run artifacts only:
  evidence/<label>/summary.json      (schema v2 — typed scalars + loop_trap),
  evidence/<label>/launcher.stdout.log (CONTEXT-ROT / PREFIX-BREAK marker lines),
  evidence/<label>/failures.log      (one line per failure).

Read-only by construction: every file is opened for reading only; the module
is NOT imported by the run path (cli/session/k8s never import it) and adds no
dependencies (stdlib only). It reports observations — no STOP thresholds, no
causation claims.

Metrics extension (host-side, evidence-metrics task 2026-10-18): a per-run
table, machine-quality eligibility (machine outcomes + an explicitly declared
acceptance.mode), context-time Σ(live_context × turn-duration) in
token-seconds from per-turn telemetry (NOT the top-level elapsed_s, which is
wall time including transport/gates), and min/median/max over eligible
records, GROUPED by acceptance.mode — "none" and "provided" are never pooled
in one sample (external review 2026-10-18; operator decision 2026-10-18:
segment the view, do NOT add a boundary field to the ticket contract). Rules held as code, not prose: an absent or invalid field is
`unknown`, never a zero; launch-level outcomes and records with an
undeclared acceptance.mode are listed separately with a reason; absence of
retry chains in a window is NOT first-pass acceptance.

CLI: python3 -m launcher.aggregate [evidence_dir]
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

# Context-size buckets for the observation summary (token ranges, half-open).
# Fixed presentation ranges, NOT thresholds: crossing a bucket boundary is an
# observation, never a verdict.
CONTEXT_BUCKETS = [(0, 20_000), (20_000, 40_000), (40_000, 60_000),
                   (60_000, 80_000), (80_000, None)]

# Launch-level rc classes (launcher/exitcodes.py contract). rc=1 is a model/
# code DEFECT; 124 is the supervisor wait timeout; everything else is a
# launch-level (infrastructure/ticket-input) failure, not a model outcome.
TIMEOUT_RC = 124
INFRA_RCS = {13, 14, 15, 16, 17, 20, 21, 22, 24, 26, 27}

# Outcomes that represent a machine run whose verdict was produced.
# INFRA/TIMEOUT/MISSING/CORRUPT are launch-level (host-side) outcomes: real
# observations, but never mixed into machine-quality views.
MACHINE_OUTCOMES = ("PASS", "NO-OP", "DEFECT")

# acceptance.mode values that mean the ticket declared its acceptance
# explicitly ("none" is a declared decision, not a gap). Anything else —
# missing block, "undeclared" — is a data-quality defect: such records stay
# in the table but never in a machine-quality denominator.
DECLARED_ACCEPTANCE = ("none", "provided")

MARKERS = ("CONTEXT-ROT", "PREFIX-BREAK")

# summary.json fields without which the record cannot be classified.
REQUIRED_KEYS = ("rc", "verifier")

_RETRY_RE = re.compile(r"^(?P<base>.+)-retry(?P<n>\d+)$")


def classify(summary: dict) -> tuple[str, str]:
    """Return (outcome, subtype) for a parsed summary.json.

    Outcomes: PASS | NO-OP | DEFECT | TIMEOUT | INFRA.
    Subtype: probe_result when present, else the rc/verifier detail.
    """
    rc = summary.get("rc")
    verifier = summary.get("verifier")
    probe = summary.get("probe_result") or ""
    if rc == 0 and verifier == "PASS":
        if probe == "NO-OP-PASS":
            return "NO-OP", probe
        return "PASS", probe
    if rc == TIMEOUT_RC:
        return "TIMEOUT", probe or "rc=124"
    if rc in INFRA_RCS:
        return "INFRA", probe or f"rc={rc}"
    # rc != 0 (incl. DEFECT=1) or verifier FAIL with rc==0
    return "DEFECT", probe or f"rc={rc} verifier={verifier}"


def max_live_context(summary: dict) -> int | None:
    """Max live_context_tokens across inference_telemetry.per_turn, else None.

    None means the run carries no per-turn context telemetry (unmeasured),
    NOT a zero.
    """
    telemetry = summary.get("inference_telemetry")
    if not isinstance(telemetry, dict):
        return None
    values = [tok for t in telemetry.get("per_turn", [])
              if isinstance(t, dict) and isinstance(tok := t.get("live_context_tokens"), int)]
    return max(values) if values else None


def context_time_seconds(summary: dict) -> float | None:
    """Σ live_context_tokens × elapsed_s over inference_telemetry.per_turn.

    A load approximation in token-seconds, NOT a GPU measurement. Sums the
    per-turn durations from telemetry; the top-level elapsed_s (wall time
    including transport/gates) is deliberately not used. Valid only when
    EVERY turn carries a non-negative int context and a non-negative numeric
    duration; otherwise None — unknown, never zero.
    """
    telemetry = summary.get("inference_telemetry")
    if not isinstance(telemetry, dict):
        return None
    turns = telemetry.get("per_turn")
    if not isinstance(turns, list) or not turns:
        return None
    total = 0.0
    for turn in turns:
        if not isinstance(turn, dict):
            return None
        ctx = turn.get("live_context_tokens")
        dur = turn.get("elapsed_s")
        if isinstance(ctx, bool) or not isinstance(ctx, int) or ctx < 0:
            return None
        if isinstance(dur, bool) or not isinstance(dur, (int, float)) or dur < 0:
            return None
        total += ctx * dur
    return total


def acceptance_mode(summary: dict):
    """acceptance.mode as recorded (None when the block is absent)."""
    acceptance = summary.get("acceptance")
    return acceptance.get("mode") if isinstance(acceptance, dict) else None


def exclusion_reason(summary: dict, outcome: str) -> str | None:
    """None → eligible for machine-quality views; else the stated reason.

    Two independent exclusions, both reported verbatim when both apply:
    a launch-level outcome (host-side, not a machine defect), and an
    acceptance.mode that was not explicitly declared (data-quality defect).
    """
    reasons = []
    if outcome not in MACHINE_OUTCOMES:
        reasons.append(f"outcome {outcome} (launch-level, not machine quality)")
    mode = acceptance_mode(summary)
    if mode not in DECLARED_ACCEPTANCE:
        reasons.append(f"acceptance.mode={mode!r} not declared")
    return "; ".join(reasons) if reasons else None


def retry_of(label: str) -> tuple[str | None, int | None]:
    """Split a label into (base_label, retry_number); (None, None) if not a retry."""
    m = _RETRY_RE.match(label)
    if not m:
        return None, None
    return m.group("base"), int(m.group("n"))


def count_markers(log_path: Path) -> dict[str, int]:
    """Count marker occurrences in a launcher.stdout.log (missing file -> zeros)."""
    counts = {m: 0 for m in MARKERS}
    if not log_path.is_file():
        return counts
    text = log_path.read_text(encoding="utf-8", errors="replace")
    for m in MARKERS:
        counts[m] = text.count(m)
    return counts


def load_record(label_dir: Path) -> dict:
    """Build one observation record for an evidence/<label>/ directory.

    outcome: PASS | NO-OP | DEFECT | TIMEOUT | INFRA | MISSING | CORRUPT.
    Never writes to any file.
    """
    label = label_dir.name
    base, retry_n = retry_of(label)
    record: dict = {
        "label": label,
        "retry_of": base,
        "retry_n": retry_n,
        "outcome": None,
        "subtype": "",
        "rc": None,
        "verifier": None,
        "probe_result": None,
        "turns": None,
        "elapsed_s": None,
        "max_live_context": None,
        "context_time_s": None,
        "acceptance_mode": None,
        "excluded_reason": "no summary.json parsed (MISSING/CORRUPT)",
        "markers": {m: 0 for m in MARKERS},
        "failures_lines": 0,
        "other_files": [],
        "note": "",
    }

    summary_path = label_dir / "summary.json"
    others = sorted(p.name for p in label_dir.iterdir()
                    if p.is_file() and p.name != "summary.json")
    record["other_files"] = others

    if not summary_path.is_file():
        record["outcome"] = "MISSING"
        record["note"] = ("empty" if not others
                         else "no summary.json; other artifacts present")
        record["markers"] = count_markers(label_dir / "launcher.stdout.log")
        return record

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        record["outcome"] = "CORRUPT"
        record["note"] = f"summary.json unreadable: {type(exc).__name__}"
        record["markers"] = count_markers(label_dir / "launcher.stdout.log")
        return record

    if not isinstance(summary, dict) or any(k not in summary for k in REQUIRED_KEYS):
        record["outcome"] = "CORRUPT"
        record["note"] = "summary.json missing required keys (rc/verifier)"
        record["markers"] = count_markers(label_dir / "launcher.stdout.log")
        return record

    outcome, subtype = classify(summary)
    record.update({
        "outcome": outcome,
        "subtype": subtype,
        "rc": summary.get("rc"),
        "verifier": summary.get("verifier"),
        "probe_result": summary.get("probe_result"),
        "turns": summary.get("turns"),
        "elapsed_s": summary.get("elapsed_s"),
        "max_live_context": max_live_context(summary),
        "context_time_s": context_time_seconds(summary),
        "acceptance_mode": acceptance_mode(summary),
        "excluded_reason": exclusion_reason(summary, outcome),
        "markers": count_markers(label_dir / "launcher.stdout.log"),
    })
    failures = label_dir / "failures.log"
    if failures.is_file():
        record["failures_lines"] = sum(
            1 for line in failures.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip())
    return record


def scan(evidence_dir: Path) -> list[dict]:
    """Scan evidence_dir (read-only) and return one record per label directory."""
    records = []
    for label_dir in sorted(p for p in evidence_dir.iterdir() if p.is_dir()):
        records.append(load_record(label_dir))
    return records


def bucket_of(tokens: int | None) -> str:
    """Bucket label for a context size; 'unmeasured' when None."""
    if not isinstance(tokens, int):
        return "unmeasured"
    for lo, hi in CONTEXT_BUCKETS:
        if tokens >= lo and (hi is None or tokens < hi):
            return f"{lo // 1000}k-{(str(hi // 1000) + 'k') if hi else 'inf'}"
    return "unmeasured"


def build_report(records: list[dict]) -> str:
    """Render the observation summary. No thresholds, no causation claims."""
    lines = [f"runs observed: {len(records)}", "", "outcomes:"]
    by_outcome: dict[str, list[dict]] = {}
    for r in records:
        by_outcome.setdefault(r["outcome"], []).append(r)
    for outcome in sorted(by_outcome):
        group = by_outcome[outcome]
        lines.append(f"  {outcome}: {len(group)}")
        subtypes: dict[str, int] = {}
        for r in group:
            key = r["subtype"] or "-"
            subtypes[key] = subtypes.get(key, 0) + 1
        for subtype, n in sorted(subtypes.items()):
            lines.append(f"    subtype {subtype}: {n}")

    lines += ["", "context-size buckets (max live_context_tokens per run):"]
    buckets: dict[str, list[dict]] = {}
    for r in records:
        buckets.setdefault(bucket_of(r["max_live_context"]), []).append(r)
    order = [f"{lo // 1000}k-{(str(hi // 1000) + 'k') if hi else 'inf'}"
             for lo, hi in CONTEXT_BUCKETS] + ["unmeasured"]
    for name in order:
        bucket = buckets.get(name)
        if not bucket:
            continue
        outcomes: dict[str, int] = {}
        for r in bucket:
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
        joined = ", ".join(f"{o}={c}" for o, c in sorted(outcomes.items()))
        lines.append(f"  {name}: n={len(bucket)} [{joined}]")

    lines += ["", "diagnostic markers (launcher.stdout.log):"]
    totals = {m: 0 for m in MARKERS}
    for r in records:
        for m in MARKERS:
            totals[m] += r["markers"].get(m, 0)
    for m in MARKERS:
        lines.append(f"  {m}: {totals[m]} occurrences")

    retries = [r for r in records if r["retry_of"]]
    lines += ["", f"retry chains: {len(retries)}"]
    for r in retries:
        lines.append(f"  {r['label']} -> retry #{r['retry_n']} of {r['retry_of']}")

    incomplete = [r for r in records if r["outcome"] in ("MISSING", "CORRUPT")]
    lines += ["", f"incomplete evidence: {len(incomplete)}"]
    for r in incomplete:
        lines.append(f"  {r['label']}: {r['outcome']} ({r['note']})")

    # --- metrics extension: table, eligibility, quantiles -----------------
    lines += ["", "per-run table (unknown = field absent/invalid, never zero):"]
    for r in records:
        lines.append(
            f"  {r['label']}: outcome={r['outcome']} subtype={r['subtype'] or '-'}"
            f" rc={r['rc']} verifier={r['verifier']} turns={r['turns']}"
            f" elapsed_s={r['elapsed_s']} max_live_context={r['max_live_context']}"
            f" context_time_s={r['context_time_s']}"
            f" acceptance={r['acceptance_mode']}"
            f" eligible={'yes' if r['excluded_reason'] is None else 'no'}")

    excluded = [r for r in records if r["excluded_reason"] is not None]
    lines += ["", f"excluded from machine-quality views: {len(excluded)}"]
    for r in excluded:
        lines.append(f"  {r['label']}: {r['excluded_reason']}")

    eligible = [r for r in records if r["excluded_reason"] is None]
    lines += ["", f"machine-quality quantiles (eligible runs: {len(eligible)}) —"
                  " sample is the retained evidence only: observations, no"
                  " thresholds, no causation, no system-wide performance claim;"
                  " absence of retry chains in a window is NOT first-pass"
                  " acceptance; grouped by acceptance.mode (modes are never"
                  " pooled in one sample; a mode without eligible runs is"
                  " omitted):"]
    for mode in DECLARED_ACCEPTANCE:
        group = [r for r in eligible if r["acceptance_mode"] == mode]
        if not group:
            continue
        lines.append(f"  acceptance={mode}: eligible runs: {len(group)}")
        for name in ("context_time_s", "max_live_context", "elapsed_s"):
            values = [r[name] for r in group
                      if not isinstance(r[name], bool)
                      and isinstance(r[name], (int, float))]
            if not values:
                lines.append(f"    {name}: unknown (no eligible record"
                             " with valid data)")
                continue
            ordered = sorted(values)
            unit = (" token-seconds (Σ live_context×turn-duration, load"
                    " approximation, not a GPU measurement)"
                    if name == "context_time_s" else "")
            lines.append(f"    {name}: n={len(ordered)} min={ordered[0]}"
                         f" median={statistics.median(ordered)}"
                         f" max={ordered[-1]}{unit}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    default = Path(__file__).resolve().parents[1] / "evidence"
    parser = __import__("argparse").ArgumentParser(
        prog="launcher.aggregate",
        description="Read-only observation summary over published evidence/.")
    parser.add_argument("evidence_dir", nargs="?", default=str(default))
    args = parser.parse_args(argv)
    evidence_dir = Path(args.evidence_dir)
    if not evidence_dir.is_dir():
        print(f"evidence dir not found: {evidence_dir}", file=sys.stderr)
        return 2
    print(build_report(scan(evidence_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
