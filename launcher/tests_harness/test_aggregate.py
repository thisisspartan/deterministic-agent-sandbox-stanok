"""G2 (2026-10-14): launcher.aggregate — read-only evidence aggregator tests.

Fixtures are synthetic evidence dirs under tmp_path (the real evidence/ is
never written to). Covers: every outcome class, missing/corrupt evidence,
read errors, context bucketing, marker counting, retry chains, and the
read-only guarantee (evidence bytes identical before/after a scan).

Metrics extension (2026-10-18): context-time Σ(live_context×turn-duration)
over per-turn telemetry (exact sum on valid data, None/unknown on every
invalid variant, never zero), acceptance-mode eligibility (declared
"none"/"provided" vs missing/"undeclared" data-quality defect),
launch-level vs machine-quality exclusion reasons, per-run table and
quantile rendering in the report.
"""
import hashlib
import json

from launcher import aggregate


def make_summary(**overrides) -> dict:
    summary = {
        "rc": 0,
        "verifier": "PASS",
        "probe_result": "CLEAN-FIRST",
        "turns": 1,
        "elapsed_s": 42.0,
        "inference_telemetry": {"per_turn": [
            {"turn": 1, "live_context_tokens": 25000},
            {"turn": 2, "live_context_tokens": 31000},
        ]},
    }
    summary.update(overrides)
    return summary


def make_evidence(tmp_path, label, *, summary=None, raw=None, extra_files=(),
                  log_text=None, failures_text=None):
    """Create evidence/<label>/; `raw` writes summary.json verbatim (corrupt)."""
    d = tmp_path / "evidence" / label
    d.mkdir(parents=True)
    if summary is not None:
        (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    elif raw is not None:
        (d / "summary.json").write_text(raw, encoding="utf-8")
    for name in extra_files:
        (d / name).write_text("artifact", encoding="utf-8")
    if log_text is not None:
        (d / "launcher.stdout.log").write_text(log_text, encoding="utf-8")
    if failures_text is not None:
        (d / "failures.log").write_text(failures_text, encoding="utf-8")
    return d


def digest_tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# --- outcome classification -------------------------------------------------

def test_classify_pass_and_noop():
    assert aggregate.classify(make_summary()) == ("PASS", "CLEAN-FIRST")
    assert aggregate.classify(make_summary(probe_result="NO-OP-PASS"))[:1] == ("NO-OP",)


def test_classify_verifier_fail_is_defect():
    outcome, _ = aggregate.classify(make_summary(rc=0, verifier="FAIL"))
    assert outcome == "DEFECT"
    outcome, sub = aggregate.classify(
        make_summary(rc=1, verifier="FAIL", probe_result="CONTRACT-FAIL"))
    assert (outcome, sub) == ("DEFECT", "CONTRACT-FAIL")


def test_classify_timeout_and_infra():
    assert aggregate.classify(make_summary(rc=124, verifier=None))[0] == "TIMEOUT"
    for rc in (16, 21, 22, 24, 27):
        assert aggregate.classify(make_summary(rc=rc, verifier=None))[0] == "INFRA"


# --- missing / corrupt evidence ---------------------------------------------

def test_missing_summary(tmp_path):
    d = make_evidence(tmp_path, "nolabel", extra_files=["launcher.stdout.log"])
    rec = aggregate.load_record(d)
    assert rec["outcome"] == "MISSING"
    assert "other artifacts" in rec["note"]


def test_empty_dir_is_missing(tmp_path):
    d = make_evidence(tmp_path, "empty")
    rec = aggregate.load_record(d)
    assert rec["outcome"] == "MISSING" and rec["note"] == "empty"


def test_corrupt_json(tmp_path):
    d = make_evidence(tmp_path, "broken", raw="{not json,,")
    rec = aggregate.load_record(d)
    assert rec["outcome"] == "CORRUPT" and "JSONDecodeError" in rec["note"]


def test_corrupt_missing_required_keys(tmp_path):
    d = make_evidence(tmp_path, "half", summary={"verifier": "PASS"})
    rec = aggregate.load_record(d)
    assert rec["outcome"] == "CORRUPT" and "required keys" in rec["note"]


def test_unreadable_summary_bytes(tmp_path):
    d = tmp_path / "evidence" / "undecodable"
    d.mkdir(parents=True)
    (d / "summary.json").write_bytes(b"\xff\xfe\x00\x01")
    rec = aggregate.load_record(d)
    assert rec["outcome"] == "CORRUPT"


# --- context telemetry and buckets ------------------------------------------

def test_max_live_context(tmp_path):
    rec = aggregate.load_record(make_evidence(tmp_path, "ctx", summary=make_summary()))
    assert rec["max_live_context"] == 31000


def test_max_live_context_absent_is_none_not_zero(tmp_path):
    summary = make_summary()
    del summary["inference_telemetry"]
    rec = aggregate.load_record(make_evidence(tmp_path, "noctx", summary=summary))
    assert rec["max_live_context"] is None
    assert aggregate.bucket_of(None) == "unmeasured"


def test_bucket_of_ranges():
    assert aggregate.bucket_of(0) == "0k-20k"
    assert aggregate.bucket_of(19_999) == "0k-20k"
    assert aggregate.bucket_of(20_000) == "20k-40k"
    assert aggregate.bucket_of(80_000) == "80k-inf"


# --- markers and retry chains ------------------------------------------------

def test_marker_counts_from_stdout_log(tmp_path):
    log = ("  [CONTEXT-ROT WARN] Live context window (90000 tokens)\n"
           "  [PREFIX-BREAK WARN] turn 3 input_tokens=88000\n"
           "  [PREFIX-BREAK WARN] turn 4 input_tokens=91000\n")
    d = make_evidence(tmp_path, "marked", summary=make_summary(), log_text=log)
    rec = aggregate.load_record(d)
    assert rec["markers"] == {"CONTEXT-ROT": 1, "PREFIX-BREAK": 2}


def test_marker_counts_absent_log_is_zero(tmp_path):
    d = make_evidence(tmp_path, "clean", summary=make_summary())
    rec = aggregate.load_record(d)
    assert rec["markers"] == {"CONTEXT-ROT": 0, "PREFIX-BREAK": 0}


def test_retry_chain_parsing(tmp_path):
    assert aggregate.retry_of("cc259-smoke-retry2") == ("cc259-smoke", 2)
    assert aggregate.retry_of("plain-label") == (None, None)
    d = make_evidence(tmp_path, "x-retry1", summary=make_summary())
    rec = aggregate.load_record(d)
    assert (rec["retry_of"], rec["retry_n"]) == ("x", 1)


# --- read-only guarantee -----------------------------------------------------

def test_scan_does_not_modify_evidence(tmp_path):
    make_evidence(tmp_path, "a", summary=make_summary(),
                  log_text="turn finished\n", failures_text="boom\n")
    make_evidence(tmp_path, "b", raw="{broken")
    make_evidence(tmp_path, "c")
    before = digest_tree(tmp_path / "evidence")
    records = aggregate.scan(tmp_path / "evidence")
    after = digest_tree(tmp_path / "evidence")
    assert before == after
    assert {r["outcome"] for r in records} == {"PASS", "CORRUPT", "MISSING"}


def test_aggregate_not_imported_by_run_path():
    """The aggregator must stay out of the runtime: no production launcher
    module (other than itself) imports it."""
    from launcher import __file__ as launcher_init
    from pathlib import Path
    launcher_dir = Path(launcher_init).parent
    import re
    import_pat = re.compile(r"^\s*(from|import)\s+\S*aggregate", re.MULTILINE)
    importers = [p.name for p in sorted(launcher_dir.glob("*.py"))
                 if p.name != "aggregate.py"
                 and import_pat.search(p.read_text(encoding="utf-8"))]
    assert importers == []


# --- report rendering ---------------------------------------------------------

def test_report_groups_outcomes_buckets_markers(tmp_path):
    make_evidence(tmp_path, "ok1", summary=make_summary())
    make_evidence(tmp_path, "ok2-retry1", summary=make_summary(
        inference_telemetry={"per_turn": [{"live_context_tokens": 65000}]}))
    make_evidence(tmp_path, "bad", summary=make_summary(
        rc=1, verifier="FAIL", probe_result="LOOP-TRAP",
        inference_telemetry={}))
    make_evidence(tmp_path, "gone")
    report = aggregate.build_report(aggregate.scan(tmp_path / "evidence"))
    assert "runs observed: 4" in report
    assert "PASS: 2" in report and "DEFECT: 1" in report and "MISSING: 1" in report
    assert "20k-40k: n=1 [PASS=1]" in report
    assert "60k-80k: n=1 [PASS=1]" in report
    assert "ok2-retry1 -> retry #1 of ok2" in report
    assert "CONTEXT-ROT: 0 occurrences" in report


def test_main_cli_reads_real_shape(tmp_path, capsys):
    make_evidence(tmp_path, "run1", summary=make_summary())
    rc = aggregate.main([str(tmp_path / "evidence")])
    out = capsys.readouterr().out
    assert rc == 0 and "runs observed: 1" in out
    rc = aggregate.main([str(tmp_path / "nope")])
    assert rc == 2


# --- metrics extension: context-time (Σ live_context × turn-duration) --------

def _telemetry(turns):
    return {"inference_telemetry": {"per_turn": [
        dict({"turn": i}, **t) for i, t in enumerate(turns, 1)]}}


def test_context_time_exact_sum_over_valid_turns():
    summary = make_summary(**_telemetry([
        {"live_context_tokens": 25000, "elapsed_s": 10.0},
        {"live_context_tokens": 31000, "elapsed_s": 20.0},
    ]))
    assert aggregate.context_time_seconds(summary) == 25000 * 10.0 + 31000 * 20.0


def test_context_time_int_durations_accepted():
    summary = make_summary(**_telemetry([{"live_context_tokens": 5, "elapsed_s": 2}]))
    assert aggregate.context_time_seconds(summary) == 10.0


def test_context_time_unknown_variants_are_none_not_zero():
    # No telemetry at all / malformed containers.
    assert aggregate.context_time_seconds({}) is None
    assert aggregate.context_time_seconds({"inference_telemetry": {}}) is None
    assert aggregate.context_time_seconds(
        {"inference_telemetry": {"per_turn": []}}) is None
    assert aggregate.context_time_seconds(
        {"inference_telemetry": {"per_turn": "oops"}}) is None
    # Any turn missing context or duration makes the whole sum unknown.
    assert aggregate.context_time_seconds(
        {"inference_telemetry": {"per_turn": [{"live_context_tokens": 1}]}}) is None
    assert aggregate.context_time_seconds(
        {"inference_telemetry": {"per_turn": [{"elapsed_s": 1.0}]}}) is None
    # Negative or bool values are invalid, not data.
    assert aggregate.context_time_seconds(
        {"inference_telemetry": {"per_turn":
            [{"live_context_tokens": -1, "elapsed_s": 1.0}]}}) is None
    assert aggregate.context_time_seconds(
        {"inference_telemetry": {"per_turn":
            [{"live_context_tokens": 1, "elapsed_s": -1.0}]}}) is None
    assert aggregate.context_time_seconds(
        {"inference_telemetry": {"per_turn":
            [{"live_context_tokens": True, "elapsed_s": True}]}}) is None


def test_context_time_defaults_without_per_turn_duration_is_none():
    # The historical telemetry shape (no per-turn elapsed_s) yields unknown.
    assert aggregate.context_time_seconds(make_summary()) is None


# --- metrics extension: acceptance-mode eligibility ---------------------------

def test_acceptance_mode_extraction():
    assert aggregate.acceptance_mode({}) is None
    assert aggregate.acceptance_mode({"acceptance": {}}) is None
    assert aggregate.acceptance_mode(
        {"acceptance": {"mode": "provided"}}) == "provided"


def test_declared_acceptance_is_eligible_including_none():
    assert aggregate.exclusion_reason(
        make_summary(acceptance={"mode": "none"}), "PASS") is None
    assert aggregate.exclusion_reason(
        make_summary(acceptance={"mode": "provided"}), "PASS") is None
    # A machine DEFECT verdict is still machine quality when declared.
    assert aggregate.exclusion_reason(
        make_summary(rc=1, verifier="FAIL",
                     acceptance={"mode": "none"}), "DEFECT") is None


def test_undeclared_or_missing_acceptance_is_excluded_with_reason():
    reason = aggregate.exclusion_reason(make_summary(), "PASS")
    assert reason is not None and "not declared" in reason
    reason = aggregate.exclusion_reason(
        make_summary(acceptance={"mode": "undeclared"}), "PASS")
    assert reason is not None and "acceptance.mode='undeclared' not declared" in reason


def test_launch_level_outcome_excluded_and_reasons_combine():
    # --background-like record: launch-level outcome AND undeclared acceptance.
    reason = aggregate.exclusion_reason(
        make_summary(rc=15, verifier=None, probe_result="EARLY-ABORT",
                     acceptance={"mode": "undeclared"}), "INFRA")
    assert "outcome INFRA (launch-level, not machine quality)" in reason
    assert "acceptance.mode='undeclared' not declared" in reason
    # Launch-level with declared acceptance: only the outcome reason.
    reason = aggregate.exclusion_reason(
        make_summary(rc=22, verifier=None, acceptance={"mode": "none"}), "INFRA")
    assert reason == "outcome INFRA (launch-level, not machine quality)"


def test_record_carries_metrics_fields(tmp_path):
    summary = make_summary(acceptance={"mode": "provided"}, **_telemetry([
        {"live_context_tokens": 25000, "elapsed_s": 10.0},
        {"live_context_tokens": 31000, "elapsed_s": 20.0},
    ]))
    rec = aggregate.load_record(make_evidence(tmp_path, "good", summary=summary))
    assert rec["context_time_s"] == 870000.0
    assert rec["acceptance_mode"] == "provided"
    assert rec["excluded_reason"] is None
    # Default fixture: no acceptance block, no per-turn durations.
    rec = aggregate.load_record(
        make_evidence(tmp_path, "legacy", summary=make_summary()))
    assert rec["context_time_s"] is None
    assert rec["acceptance_mode"] is None
    assert rec["excluded_reason"] and "not declared" in rec["excluded_reason"]


# --- metrics extension: report table, exclusions, quantiles ------------------

def _make_run(tmp_path, label, *, ctx, elapsed, acceptance,
              rc=0, verifier="PASS", probe="CLEAN-FIRST"):
    """One synthetic eligible/excluded run with full valid telemetry."""
    summary = {
        "rc": rc, "verifier": verifier, "probe_result": probe, "turns": 1,
        "elapsed_s": elapsed,
        "inference_telemetry": {"per_turn": [
            {"live_context_tokens": ctx, "elapsed_s": elapsed}]},
    }
    if acceptance is not None:
        summary["acceptance"] = {"mode": acceptance}
    make_evidence(tmp_path, label, summary=summary)


def test_report_metrics_table_exclusions_and_quantiles(tmp_path):
    _make_run(tmp_path, "ok1", ctx=1000, elapsed=10.0, acceptance="none")
    _make_run(tmp_path, "ok2", ctx=2000, elapsed=20.0, acceptance="provided")
    _make_run(tmp_path, "ok3", ctx=3000, elapsed=30.0, acceptance="none")
    # --background-like launch-level record (real shape: empty per_turn).
    make_evidence(tmp_path, "aborted", summary={
        "rc": 15, "verifier": None, "probe_result": "EARLY-ABORT",
        "turns": 0, "elapsed_s": 0.0,
        "inference_telemetry": {"per_turn": []},
        "acceptance": {"mode": "undeclared"},
    })
    report = aggregate.build_report(aggregate.scan(tmp_path / "evidence"))

    assert "per-run table (unknown = field absent/invalid, never zero):" in report
    line = next(l for l in report.splitlines() if l.strip().startswith("aborted:"))
    assert "eligible=no" in line and "context_time_s=None" in line
    good = next(l for l in report.splitlines() if l.strip().startswith("ok1:"))
    assert "eligible=yes" in good and "context_time_s=10000.0" in good

    assert "excluded from machine-quality views: 1" in report
    assert ("aborted: outcome INFRA (launch-level, not machine quality); "
            "acceptance.mode='undeclared' not declared") in report

    assert "machine-quality quantiles (eligible runs: 3)" in report
    # per-turn duration == the run's elapsed_s here: ctx×dur = 10000/40000/90000.
    assert ("context_time_s: n=3 min=10000.0 median=40000.0 max=90000.0"
            " token-seconds") in report
    assert "max_live_context: n=3 min=1000 median=2000 max=3000" in report
    assert "elapsed_s: n=3 min=10.0 median=20.0 max=30.0" in report


def test_quantiles_render_unknown_when_no_valid_values(tmp_path):
    # Eligible record, but its telemetry carries no usable numbers.
    summary = make_summary(acceptance={"mode": "none"},
                           inference_telemetry={"per_turn": []})
    make_evidence(tmp_path, "novalue", summary=summary)
    report = aggregate.build_report(aggregate.scan(tmp_path / "evidence"))
    assert "machine-quality quantiles (eligible runs: 1)" in report
    assert "context_time_s: unknown (no eligible record with valid data)" in report
    assert "max_live_context: unknown (no eligible record with valid data)" in report


def test_missing_fields_render_as_none_not_zero_in_table(tmp_path):
    summary = make_summary(acceptance={"mode": "none"})
    del summary["inference_telemetry"]
    make_evidence(tmp_path, "bare", summary=summary)
    report = aggregate.build_report(aggregate.scan(tmp_path / "evidence"))
    line = next(l for l in report.splitlines() if l.strip().startswith("bare:"))
    assert "max_live_context=None" in line and "context_time_s=None" in line
    assert "eligible=yes" in line
