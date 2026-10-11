"""CC-237 (schema v2, operator decision 2026-10-11): summary.json is TYPED.

The operator's fix direction: "правильный фикс — добавить поле в схему, а не
править протокол под код". The cc236 incident showed the protocol had to be
read around the summary's gaps (free-text errors, no loop_trap, telemetry 0
on a trap run). Schema v2 closes that:

  1  build_summary emits EXACTLY the allowlist — scalars and structured
     fields only; no free-text keys (errors / failures /
     contract_lock_violations are GONE from summary.json).
  2  loop_trap is the typed circuit-breaker record
     {"tool": str, "hash": str, "n": int} | None — extra marker keys (ts)
     are dropped, anything malformed publishes None.
  3  all free text of a run goes to failures.log — one line per failure
     (the error string, verify_gate failures, contract-lock violations);
     a clean run writes no failures.log.
  4  write_env_fail_summary: the ENV-FAIL verdict stays typed, the error
     text lives in failures.log.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_summary_schema.py -q
"""
import json
import os
import pathlib

import pytest

from launcher import summary
from launcher.config import Config

# The exact output keys of build_summary (docstring of summary.py).
# patch_sha256 is host-stamped in k8s mode only (k8s.py), not by build_summary.
ALLOWLIST = {
    "label", "ticket", "rc", "verifier", "probe_result", "turns", "elapsed_s",
    "session_id", "commit_sha", "tokens", "cache_hit_rate",
    "inference_telemetry", "tool_activity", "loop_trap", "opik_traces",
}

FULL_JOB = {
    "label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
    "turns": 1, "session_id": "s-1",
    "tokens": {"input_tokens": 10, "output_tokens": 5},
    "cache_hit_rate": "96.4%",
    "turn_telemetry": [{"turn": 1, "elapsed_s": 12.0, "bash_total": 3,
                        "bash_ok": 2}],
    "tool_activity": {"bash_total": 3, "bash_ok": 2},
    "loop_trap": None,
    "opik_traces": ["trace-1"],
}


def _host_cfg(tmp_path, monkeypatch):
    """Host-side routing (no STANOK_IN_CONTAINER): summary_dir -> the
    evidence dir. STANOK_START_COMMIT set: no provenance WARN noise."""
    repo = tmp_path / "repo"
    repo.mkdir()
    log = tmp_path / "logs"
    log.mkdir()
    monkeypatch.delenv("STANOK_IN_CONTAINER", raising=False)
    monkeypatch.setenv("STANOK_START_COMMIT", "0" * 40)
    return Config(repo_root=str(repo), log_dir=str(log))


def _failures(cfg, label):
    p = os.path.join(cfg.repo_root, "evidence", label, "failures.log")
    if not os.path.isfile(p):
        return None
    return [line for line in open(p, encoding="utf-8").read().splitlines()
            if line]


# --- 1: the allowlist is exact, the types are typed ------------------------------

def test_build_summary_emits_exactly_the_allowlist(monkeypatch):
    monkeypatch.setenv("STANOK_START_COMMIT", "0" * 40)
    s = summary.build_summary(Config(repo_root="/nonexistent"), dict(FULL_JOB), 7)
    assert set(s) == ALLOWLIST
    assert s["label"] == "lbl" and s["ticket"] == "t.md"
    assert type(s["rc"]) is int and s["rc"] == 0
    assert s["verifier"] == "PASS" and s["probe_result"] == "CLEAN-FIRST"
    assert type(s["turns"]) is int and type(s["elapsed_s"]) is int
    assert s["session_id"] == "s-1"
    assert s["commit_sha"] == "0" * 40
    assert isinstance(s["tokens"], dict) and s["cache_hit_rate"] == "96.4%"
    it = s["inference_telemetry"]
    assert isinstance(it, dict) and it["aggregate"]["turns"] == 1
    assert s["tool_activity"] == {"bash_total": 3, "bash_ok": 2}
    assert s["loop_trap"] is None
    assert s["opik_traces"] == ["trace-1"]


# --- 2: loop_trap is the typed triple or None ------------------------------------

VALID_TRAP = {"tool": "Bash", "hash": "a" * 64, "n": 5}

TRAP_CASES = [
    # the real marker shape (the hook adds ts) -> ts dropped, triple kept
    ({"tool": "Bash", "hash": "a" * 64, "n": 5, "ts": "2026-10-07T12:00:00"},
     VALID_TRAP),
    (VALID_TRAP, VALID_TRAP),
    # malformed -> None (the protocol reads None as "no trap")
    ({"tool": "Bash", "hash": "a" * 64, "n": True}, None),   # bool is not int
    ({"tool": 123, "hash": "a" * 64, "n": 5}, None),         # tool must be str
    ({"tool": "Bash", "hash": 7, "n": 5}, None),             # hash must be str
    ({"tool": "Bash", "n": 5}, None),                         # missing hash
    ({"hash": "a" * 64, "n": 5}, None),                      # missing tool
    ("not a dict", None),
    (42, None),
    (None, None),
    ({}, None),
]


@pytest.mark.parametrize("trap,expected", TRAP_CASES)
def test_loop_trap_field_is_typed(trap, expected, monkeypatch):
    monkeypatch.setenv("STANOK_START_COMMIT", "0" * 40)
    job = dict(FULL_JOB, loop_trap=trap)
    s = summary.build_summary(Config(repo_root="/nonexistent"), job, 0)
    assert s["loop_trap"] == expected


# --- 3: free text never enters summary.json --------------------------------------

def test_summary_has_no_free_text_keys(monkeypatch):
    monkeypatch.setenv("STANOK_START_COMMIT", "0" * 40)
    job = dict(FULL_JOB, rc=1, verifier="FAIL",
               error="boom",
               failures=[("suite", "FAILED test_x")],
               contract_lock_violations=["MODIFIED: tests/t_test.py"])
    s = summary.build_summary(Config(repo_root="/nonexistent"), job, 0)
    assert set(s) == ALLOWLIST  # no errors / failures / contract_lock_violations
    # decide()'s priority is unchanged: the contract violation still wins
    assert s["probe_result"] == "CONTRACT-FAIL"


# --- 4: failures.log carries the text, one line per failure ----------------------

def test_write_summary_writes_failures_log(tmp_path, monkeypatch):
    cfg = _host_cfg(tmp_path, monkeypatch)
    job = dict(FULL_JOB, label="lbl", rc=1, verifier="FAIL",
               error="boom",
               failures=[("suite", "FAILED test_x"), "plain string"],
               contract_lock_violations=["MODIFIED: tests/t_test.py"])
    summary.write_summary(cfg, job, 0)
    s = json.loads(pathlib.Path(cfg.repo_root, "evidence", "lbl", "summary.json")
                   .read_text(encoding="utf-8"))
    assert set(s) == ALLOWLIST
    assert _failures(cfg, "lbl") == [
        "boom",
        "suite: FAILED test_x",
        "plain string",
        "MODIFIED: tests/t_test.py",
    ]


def test_clean_run_writes_no_failures_log(tmp_path, monkeypatch):
    cfg = _host_cfg(tmp_path, monkeypatch)
    summary.write_summary(cfg, dict(FULL_JOB, label="lbl"), 0)
    assert _failures(cfg, "lbl") is None
    assert not os.path.exists(
        os.path.join(cfg.repo_root, "evidence", "lbl", "failures.log"))


# --- 5: ENV-FAIL stays typed; the error text is in failures.log ------------------

def test_env_fail_summary_text_goes_to_failures_log(tmp_path, monkeypatch):
    cfg = _host_cfg(tmp_path, monkeypatch)
    summary.write_env_fail_summary(cfg, "lbl", "fresh check could not run: EXEC_ERROR")
    s = json.loads(pathlib.Path(cfg.repo_root, "evidence", "lbl", "summary.json")
                   .read_text(encoding="utf-8"))
    assert set(s) == ALLOWLIST
    assert s["probe_result"] == "ENV-FAIL" and s["rc"] == 16
    assert _failures(cfg, "lbl") == ["fresh check could not run: EXEC_ERROR"]
