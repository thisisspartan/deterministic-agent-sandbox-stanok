"""G2 (2026-10-14): launcher.aggregate — read-only evidence aggregator tests.

Fixtures are synthetic evidence dirs under tmp_path (the real evidence/ is
never written to). Covers: every outcome class, missing/corrupt evidence,
read errors, context bucketing, marker counting, retry chains, and the
read-only guarantee (evidence bytes identical before/after a scan).
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
