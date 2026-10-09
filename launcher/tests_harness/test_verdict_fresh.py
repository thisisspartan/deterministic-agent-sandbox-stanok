"""Stage 3 T3-5 — the host issues the final verdict (SPEC-VERDICT-INTEGRITY §2),
S2-simplified (PLAN-SIMPLIFY-2026-10-09): the I5 detector, the worker_*
fields and the INTEGRITY-FAIL value are REMOVED. The host's authority is its
two independent checks only: the contract recompute and the fresh check.

`_publish_evidence(cfg, label, container_rc, contract_violations=(),
fresh_check=None)`: the final verifier/rc/probe_result are issued by the HOST
with the priority CONTRACT-FAIL > FRESH-FAIL > the worker's claims (which
pass through untouched when neither host check fires):
  - `fresh_check=(rc, tail)` is `verify.fresh_verify`'s result — the host's
    independent re-run of the suite in a fresh container the worker never
    touched (T3-3). A non-zero fresh rc forces verifier=FAIL +
    probe_result=FRESH-FAIL + rc=fresh rc; the tail is appended to errors.
    fresh_check=None = not run.
  - the worker's summary is published as-is when no host check fires — the
    host never cross-checks the worker's rc against the container exit
    (sanctioned gap, S2): the verdict is a statement about the TREE
    (suite green + tree = declared), not about the worker's self-report.
decide()/_status_fields unchanged.

Tests:
  1  CONTRACT-FAIL beats a worker PASS even when the fresh check passes
  2  CONTRACT-FAIL beats FRESH-FAIL (spec priority)
  3  FRESH-FAIL at worker PASS -> final FAIL + probe FRESH-FAIL + rc=fresh
     rc + tail in errors
  4  FRESH-FAIL fires on a forged worker (claims PASS, container exited 1)
  5  FRESH-FAIL outranks the worker's own honest FAIL (priority over the
     worker's claims)
  6  pure forgery (claims PASS, container exited 1) with clean tree + fresh
     PASS -> published unchanged — the S2-sanctioned gap: no I5 check
  7  clean path (worker PASS, container 0, fresh PASS) -> summary unchanged,
     no worker_* fields (CLEAN-FIRST)
  8  same for PASS-AFTER-LOCAL-RETRY (turns=2)
  9  fresh_check=None (not run) -> the worker's claims pass through
  10 CONTRACT-FAIL overrides the NO-OP-PASS session-override label (spec R2)
  11 FRESH-FAIL overrides the NO-OP-PASS label (spec §3 priority, R2)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_verdict_fresh.py -q
"""
import json

from launcher import summary
from launcher.config import Config

CLEAN_WORKER = {"rc": 0, "verifier": "PASS", "probe_result": "CLEAN-FIRST",
                "contract_lock_violations": [], "errors": [], "failures": []}


def _publish_tree(tmp_path, label, summary_dict):
    repo = tmp_path / "repo"
    logdir = tmp_path / "logs"
    live = logdir / label
    live.mkdir(parents=True)
    (live / "summary.json").write_text(json.dumps(summary_dict), encoding="utf-8")
    return repo, logdir


def _cfg(repo, logdir):
    return Config(repo_root=str(repo), log_dir=str(logdir))


def _published(repo, label):
    return json.loads(
        (repo / "evidence" / label / "summary.json").read_text(encoding="utf-8"))


# --- 1-2: CONTRACT-FAIL outranks everything -------------------------------------

def test_contract_fail_beats_worker_pass_even_with_fresh_pass(tmp_path):
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(CLEAN_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 0,
                             ["MODIFIED: tests/t_test.py"], (0, ""))
    dst = _published(repo, "lbl")
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"


def test_contract_fail_beats_fresh_fail(tmp_path):
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(CLEAN_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 0,
                             ["MODIFIED: tests/t_test.py"],
                             (1, "FAILED tests/t_test.py::test_x"))
    dst = _published(repo, "lbl")
    assert dst["probe_result"] == "CONTRACT-FAIL"


# --- 3-5: FRESH-FAIL — the host's independent check failed ----------------------

def test_fresh_fail_overrides_worker_pass(tmp_path):
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(CLEAN_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 0, (),
                             (1, "FAILED tests/t_test.py::test_x - 1 == 2"))
    dst = _published(repo, "lbl")
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "FRESH-FAIL"
    # the final rc is the fresh check's own exit — the host's measurement
    assert dst["rc"] == 1
    assert any("1 == 2" in e for e in dst["errors"])


def test_fresh_fail_fires_on_forged_worker(tmp_path):
    # S2: the worker claims rc=0/PASS while the container exited 1, and the
    # fresh check fails — the host's fresh check is the only override and it
    # fires regardless of the worker's claim.
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(CLEAN_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 1, (),
                             (1, "FAILED tests/t_test.py::test_x"))
    dst = _published(repo, "lbl")
    assert dst["probe_result"] == "FRESH-FAIL"


def test_fresh_fail_outranks_worker_own_fail(tmp_path):
    # The worker honestly failed; the fresh check confirms it — the host's
    # independent verdict is the one issued (priority: FRESH-FAIL > worker
    # override).
    worker = {"rc": 1, "verifier": "FAIL", "probe_result": "VERIFY-FAIL",
              "errors": [], "failures": []}
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(worker))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 1, (),
                             (1, "FAILED tests/t_test.py::test_x"))
    dst = _published(repo, "lbl")
    assert dst["probe_result"] == "FRESH-FAIL"


# --- 6: the S2-sanctioned gap: a pure forgery is no longer caught ---------------

def test_forged_worker_not_caught_after_s2(tmp_path):
    # S2 (PLAN-SIMPLIFY-2026-10-09): the host's authority is its two checks
    # only. A worker claiming rc=0/PASS while the container exited 1, over a
    # clean contract with a GREEN fresh check, is published unchanged — the
    # I5 rc cross-check is gone. The verdict is a statement about the tree
    # (suite green + tree = declared), not about the worker's self-report.
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(CLEAN_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 1, (), (0, ""))
    dst = _published(repo, "lbl")
    assert dst == CLEAN_WORKER
    assert "integrity_violation" not in dst
    assert "worker_rc" not in dst


# --- 7-9: the clean path stays byte-identical ------------------------------------

def test_clean_path_unchanged(tmp_path):
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(CLEAN_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 0, (), (0, ""))
    dst = _published(repo, "lbl")
    assert dst == CLEAN_WORKER
    assert "worker_rc" not in dst
    assert "worker_verifier" not in dst


def test_pass_after_local_retry_unchanged(tmp_path):
    worker = {"rc": 0, "verifier": "PASS", "probe_result": "PASS-AFTER-LOCAL-RETRY",
              "turns": 2, "contract_lock_violations": [], "errors": [],
              "failures": []}
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(worker))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 0, (), (0, ""))
    assert _published(repo, "lbl") == worker


def test_fresh_check_absent_keeps_today_behavior(tmp_path):
    # fresh_check=None (not run): with no host check firing, the worker's
    # claims pass through untouched.
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(CLEAN_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 0)
    assert _published(repo, "lbl") == CLEAN_WORKER


# --- 10-11: the host overrides beat the session-override labels (spec R2) ------

NOOP_WORKER = {"rc": 1, "verifier": "PASS", "probe_result": "NO-OP-PASS",
               "contract_lock_violations": [], "errors": [], "failures": []}


def test_contract_fail_overrides_noop_pass(tmp_path):
    # Spec §3: CONTRACT-FAIL outranks every behavioral override — NO-OP-PASS
    # describes the model's behavior, the contract violation the integrity of
    # the verdict. The intentional rc=1+PASS of a NO-OP does not save it.
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(NOOP_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 1,
                             ["MODIFIED: tests/t_test.py"], (0, ""))
    dst = _published(repo, "lbl")
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert dst["verifier"] == "FAIL"


def test_fresh_fail_overrides_noop_pass(tmp_path):
    # Spec §3: FRESH-FAIL outranks the session-override label — a NO-OP claim
    # ("the artifacts pre-existed and really pass") refuted by the host's
    # independent fresh run is a defect, not a NO-OP.
    repo, logdir = _publish_tree(tmp_path, "lbl", dict(NOOP_WORKER))
    summary._publish_evidence(_cfg(repo, logdir), "lbl", 1, (),
                             (1, "FAILED tests/t_test.py::test_x - 1 == 2"))
    dst = _published(repo, "lbl")
    assert dst["probe_result"] == "FRESH-FAIL"
    assert dst["verifier"] == "FAIL"
    assert dst["rc"] == 1
