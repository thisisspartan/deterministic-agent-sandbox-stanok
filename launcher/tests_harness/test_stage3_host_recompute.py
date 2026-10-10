"""Stage 3 T3-2 — host-side contract recompute AFTER the container exits.

The second half of the trust boundary (SPEC-VERDICT-INTEGRITY §1; T3-1 took
the snapshot before `docker run`, in host memory): after the container exits
the host recomputes the protected-files manifest and compares it with the
snapshot. Any violation (a pre-existing protected file DELETED or MODIFIED)
forces `probe_result = CONTRACT-FAIL` and the final FAIL, regardless of what
the worker's summary.json claims — the verdict is issued by the host, not by
the defendant (the forged-summary scenario in test_scenarios_verdict.py).

The comparison is the same logic as `_check_contract_lock` (extracted to
`_compare_manifests`, the one source), but without the job/turn context:
this is the host's independent second check. T3-9 changed the new-file rule:
a new file under tests/ is a violation UNLESS the ticket declared it — the
declared list is passed to `host_contract_check` for exactly that
distinction (see test_stage3_tests_tree.py for the structural rule).

Tests:
  1  clean tree: no violations; a DECLARED new test after the snapshot is
     not a violation; the published summary is untouched (worker PASS kept)
  2  protected file MODIFIED / DELETED after the snapshot -> violations
  3  worker summary claims PASS (CLEAN-FIRST, rc=0): the host still forces
     verifier=FAIL + probe_result=CONTRACT-FAIL

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_host_recompute.py -q
"""
import json
from pathlib import Path

from launcher import summary, verify
from launcher.config import Config

CLEAN_WORKER = {"rc": 0, "verifier": "PASS", "probe_result": "CLEAN-FIRST",
                "contract_lock_violations": []}


def _tree(tmp_path, label, summary_dict):
    """repo with protected files + a worker summary written to LOG_DIR/<label>
    (the container-side writer's output, exactly as _publish_evidence finds
    it)."""
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    pass\n",
                                               encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    logdir = tmp_path / "logs"
    live = logdir / label
    live.mkdir(parents=True)
    (live / "summary.json").write_text(json.dumps(summary_dict), encoding="utf-8")
    return repo, Config(repo_root=str(repo), log_dir=str(logdir))


def _published(cfg, label):
    return json.loads(
        (Path(cfg.repo_root) / "evidence" / label / "summary.json")
        .read_text(encoding="utf-8"))


# --- 1: clean tree stays green --------------------------------------------------

def test_clean_tree_no_violations(tmp_path):
    repo, cfg = _tree(tmp_path, "lbl", CLEAN_WORKER)
    before = verify.contract_snapshot(cfg)
    # A DECLARED new test after the snapshot is not a violation (T3-9).
    (repo / "tests" / "new_test.py").write_text("def test_new():\n    pass\n",
                                                 encoding="utf-8")
    assert verify.host_contract_check(cfg, before, ("tests/new_test.py",)) == []
    summary._publish_evidence(cfg, "lbl", 0, [])
    dst = _published(cfg, "lbl")
    assert dst["verifier"] == "PASS"
    assert dst["probe_result"] == "CLEAN-FIRST"


# --- 2: tampering is detected ---------------------------------------------------

def test_tampered_protected_files_are_violations(tmp_path):
    repo, cfg = _tree(tmp_path, "lbl", CLEAN_WORKER)
    before = verify.contract_snapshot(cfg)
    (repo / "tests" / "t_test.py").write_text("tampered after snapshot\n",
                                               encoding="utf-8")
    (repo / "scripts" / "run.sh").unlink()
    v = verify.host_contract_check(cfg, before, ())
    assert "MODIFIED: tests/t_test.py" in v
    assert "DELETED: scripts/run.sh" in v


# --- 3: the host outranks the worker's PASS -------------------------------------

def test_host_forces_fail_over_worker_pass(tmp_path):
    repo, cfg = _tree(tmp_path, "lbl", CLEAN_WORKER)
    before = verify.contract_snapshot(cfg)
    (repo / "tests" / "t_test.py").write_text("tampered after snapshot\n",
                                               encoding="utf-8")
    violations = verify.host_contract_check(cfg, before, ())
    summary._publish_evidence(cfg, "lbl", 0, violations)
    dst = _published(cfg, "lbl")
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert any("MODIFIED: tests/t_test.py" in x
               for x in dst["contract_lock_violations"])
