"""S6a — end-to-end scenarios of the verdict path (PLAN-SIMPLIFY-2026-10-09;
rewritten onto the k8s runtime by CC-258 — the Docker path is removed).

The verdict path that survives: the host snapshots the contract before the
run; the worker's tree changes arrive as changes.patch and are recomputed on
a SCRATCH copy (the live tree is untouched during the run); the host runs the
fresh check in a Job the worker never touched; the host publishes the verdict.
These scenarios test ONLY the observable verdict — the published
evidence/<label>/summary.json, failures.log and the run's exit rc — never an
internal mechanism.

Discipline (operator, 2026-10-09, unchanged):
  - they assert the verdict, not code correctness (ARCHITECTURE.md "What PASS
    means"): a green scenario means the tree passed the host's checks;
  - they NEVER read worker_rc / worker_verifier / INTEGRITY-FAIL;
  - CC-237 (schema v2): summary.json is typed; the free text of a verdict
    (CONTRACT-LOCK / FRESH-CHECK / ENV-FAIL explanations) is observable in
    failures.log next to it — scenarios 3-6 assert it there.

Harness (CC-258): host_launch_k8s with the cluster cycle mocked (kubectl,
Pod stream, fresh Job, image provenance); the REAL transport (git fixture +
pack_tree), patch gate, scratch contract recompute, fresh gating and publish
run. The worker's mid-run tampering arrives the k8s way: as changes.patch in
the evidence payload, applied to the scratch tree. The published summary
carries the host stamps (patch_sha256, image_digest, acceptance — G4: the
host's own ticket parse, the Pod is not its own judge) — scenarios 1/7/10
assert them and that the worker's own fields pass through untouched.

Scenarios:
  1 honest PASS: clean tree, clean worker payload, fresh green -> published
    PASS (worker fields untouched + host stamps), fresh ran;
  2 retry after failure: the worker's local retry ended PASS-AFTER-LOCAL-RETRY,
    tree intact, fresh green -> published PASS, the worker's flow preserved;
  3 contract violation: an undeclared new file under src/ or tests/ via
    changes.patch -> CONTRACT-FAIL, fresh skipped (both zones, one rule);
  4 fresh check failure: the worker claims a clean PASS but the host's fresh
    Job fails the suite -> FRESH-FAIL, rc = the fresh check's rc;
  5 infrastructure failure: the fresh check cannot run (EXEC_ERROR) -> rc=16
    ENV-FAIL summary — not a verdict, call the human;
  6 forged summary over a tampered tree: changes.patch weakens an existing
    protected test while the payload claims a clean PASS -> the host recompute
    forces CONTRACT-FAIL; a host-issued verdict never exits 0;
  7 honest worker FAIL, fresh green: the host's fresh check passes over the
    final tree -> the honest FAIL is published unchanged; a green fresh check
    never fabricates a PASS (the host only downgrades, never upgrades);
  8 no evidence payload block: the run is treated as aborted (status
    'missing'), nothing is published, rc=17;
  9 declared new test keeps PASS (moved from test_stage3_tests_tree.py):
    the ticket declares the new test file, the Pod creates it via
    changes.patch -> the scratch recompute sees the declared path, no
    violation, the fresh check runs, the PASS stands and the declared
    deliverable lands in the live tree (the clean-path apply);
  10 acceptance contract is host-stamped (G4): the published acceptance
    record comes from the host's parse of the ticket, not from the worker's
    payload;
  11 B5 (review 2026-10-17): the k8s path self-validates the ticket
    contract — an empty-declared ticket without `reset: none` is refused
    before any cluster call (rc=13 EARLY-ABORT, the cli gate's code);
  12 A5: patch identity mismatch immediately before the live apply ->
    rc=16 ENV-FAIL, the deliverable does NOT land (the old WARN kept
    publishing rc=0/PASS with the patch unapplied);
  13 A5: the live `git apply` fails -> rc=16 ENV-FAIL, the live tree keeps
    its foreign content (same downgrade, natural failure).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_scenarios_verdict.py -q
"""
import argparse
import hashlib
import json
import os
import subprocess

import pytest

from launcher import k8s
from launcher.config import Config

# CC-237 (schema v2): the worker summary is TYPED — no errors/failures/
# contract_lock_violations keys; the free text lives in failures.log.
CLEAN_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
                "probe_result": "CLEAN-FIRST", "turns": 1, "loop_trap": None}

RETRY_WORKER = dict(CLEAN_WORKER, probe_result="PASS-AFTER-LOCAL-RETRY",
                    turns=2)

HONEST_FAIL_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 1,
                      "verifier": "FAIL", "probe_result": "VERIFY-FAIL",
                      "turns": 1, "loop_trap": None}

FIXED_NONCE = "0123456789abcdef0123456789abcdef"
FAKE_IMAGE = "192.168.122.156:5000/stanok-machine@sha256:fake"


def _repo(tmp_path):
    """The git fixture host_launch_k8s needs: pack_tree runs `git archive
    HEAD` and the scratch recompute applies the payload patch to that tree."""
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    assert 1 == 1\n",
                                               encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                    capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "base")
    logdir = tmp_path / "logs"
    logdir.mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(logdir))


def _published(repo):
    return json.loads((repo / "evidence" / "lbl" / "summary.json")
                      .read_text(encoding="utf-8"))


def _published_failures(repo):
    """CC-237: the published failure lines (failures.log); absent -> []."""
    p = repo / "evidence" / "lbl" / "failures.log"
    if not p.is_file():
        return []
    return [line for line in p.read_text(encoding="utf-8").splitlines() if line]


def _new_file_patch(rel, body):
    """A valid git new-file patch (same form as test_k8s_contract_scratch)."""
    lines = body.splitlines()
    n = len(lines)
    return (f"diff --git a/{rel} b/{rel}\n"
            f"new file mode 100644\n"
            f"--- /dev/null\n"
            f"+++ b/{rel}\n"
            f"@@ -0,0 +1,{n} @@\n"
            + "".join(f"+{ln}\n" for ln in lines))


# The classic forgery patch: weakens the existing protected test.
_WEAKEN_PATCH = (
    "diff --git a/tests/t_test.py b/tests/t_test.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/tests/t_test.py\n"
    "+++ b/tests/t_test.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def test_x():\n"
    "-    assert 1 == 1\n"
    "+    pass\n")


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _k8s_scenario(tmp_path, monkeypatch, *, worker_summary=CLEAN_WORKER,
                  patch_text="", fresh_result=(0, ""), payload=True,
                  ticket_text="# scenario\n\nreset: none\n"):
    """host_launch_k8s with the cluster cycle mocked; the REAL transport,
    patch gate, scratch contract recompute, fresh gating and publish run.

    worker_summary / patch_text: the Pod's evidence payload; fresh_result:
    what k8s._fresh_job returns; payload=False: the Pod produced no evidence
    block; ticket_text: the ticket manifest (default: `reset: none` — a
    valid no-deliverable ticket with NO declared paths, so every new file
    the patch creates is undeclared; B5 review 2026-10-17: host_launch_k8s
    now refuses an empty-declared ticket without `reset: none`). Returns (repo, cfg,
    args, calls) — calls records the kubectl verbs and "fresh" (whether the
    fresh Job ran)."""
    repo, cfg = _repo(tmp_path)
    ticket = tmp_path / "ticket.md"
    ticket.write_text(ticket_text, encoding="utf-8")
    args = argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket), local_retries=0, extra=[])
    calls = []

    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(k8s, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "_image_ref", lambda cfg: (FAKE_IMAGE, None))
    monkeypatch.setattr(k8s, "new_nonce", lambda: FIXED_NONCE)
    monkeypatch.setattr(k8s, "_install_signal_handlers", lambda rs: None)

    def fake_kubectl(*a, **k):
        calls.append(a[0] if a else "")
        return _FakeCompleted(0)
    monkeypatch.setattr(k8s, "_kubectl", fake_kubectl)
    monkeypatch.setattr(k8s, "_pod_of_job", lambda *a, **k: "pod-x")

    def fake_stream(pod, ns, path, deadline):
        if not payload:
            text = "worker stdout without any evidence block\n"
        else:
            files = {"summary.json": json.dumps(worker_summary).encode("utf-8")}
            if patch_text:
                files["changes.patch"] = patch_text.encode("utf-8")
            text = (k8s.begin_marker(FIXED_NONCE) + "\n"
                    + k8s.build_payload(files) + "\n"
                    + k8s.end_marker(FIXED_NONCE) + "\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    monkeypatch.setattr(k8s, "_stream_pod_logs", fake_stream)
    monkeypatch.setattr(k8s, "_wait_job_terminal", lambda *a, **k: "complete")
    monkeypatch.setattr(k8s, "_pod_image_id", lambda pod, ns: FAKE_IMAGE)

    def fake_fresh(*a, **k):
        calls.append("fresh")
        return fresh_result
    monkeypatch.setattr(k8s, "_fresh_job", fake_fresh)

    return repo, cfg, args, calls


def _run(tmp_path, monkeypatch, **kw):
    repo, cfg, args, calls = _k8s_scenario(tmp_path, monkeypatch, **kw)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    return repo, cfg, calls, rc


# --- 1: honest PASS ---------------------------------------------------------------

def test_scenario_honest_pass(tmp_path, monkeypatch):
    repo, cfg, calls, rc = _run(tmp_path, monkeypatch)
    assert rc == 0
    dst = _published(repo)
    # The host stamps (Package 1 patch identity, image provenance) are part
    # of the k8s-mode verdict; the worker's own fields pass through untouched.
    assert dst.pop("patch_sha256") == hashlib.sha256(b"").hexdigest()
    assert dst.pop("image_digest") == FAKE_IMAGE
    # G4: acceptance is host-stamped too — the host's parse of THIS ticket
    # (it declares no accept line) -> the typed default, never the worker's
    # claim.
    assert dst.pop("acceptance") == {"mode": "undeclared", "paths": []}
    # Resource measurement (operator 2026-10-16): host-stamped like the three
    # above. In this mocked cluster no kubelet sample can succeed (the mocked
    # kubectl answers nothing parseable) -> explicit None, never a 0.
    assert dst.pop("resource_peaks") == {"worker": None, "fresh": None}
    assert dst == CLEAN_WORKER  # clean path: the host does not touch the rest
    assert "fresh" in calls


# --- 2: retry after failure -------------------------------------------------------

def test_scenario_retry_after_failure_publishes_pass(tmp_path, monkeypatch):
    # The worker's in-session local retry (red turn -> fix) is the worker's
    # feedback loop, not the verdict. The observable contract: a clean final
    # tree + green fresh check publishes the worker's flow unchanged.
    repo, cfg, calls, rc = _run(tmp_path, monkeypatch,
                                worker_summary=RETRY_WORKER)
    assert rc == 0
    dst = _published(repo)
    assert dst["verifier"] == "PASS"
    assert dst["probe_result"] == "PASS-AFTER-LOCAL-RETRY"
    assert dst["rc"] == 0
    assert "fresh" in calls


# --- 3: contract violation (one rule, both zones) ----------------------------------

@pytest.mark.parametrize("rel", ["src/colorsys.py", "tests/colorsys.py"])
def test_scenario_undeclared_new_file_both_zones(tmp_path, monkeypatch, rel):
    # The k8s form of the mid-run substitution: the worker's tree change
    # arrives as changes.patch; the scratch recompute sees the undeclared file.
    repo, cfg, calls, rc = _run(
        tmp_path, monkeypatch,
        patch_text=_new_file_patch(rel, "def rgb(*a):\n    return (0, 0, 0)"))
    assert rc == 1  # a host-issued FAIL never exits 0
    dst = _published(repo)
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert any(f"UNDECLARED: {rel}" in x for x in _published_failures(repo))
    assert "fresh" not in calls  # a fresh run over a tampered tree is uninformative
    # The defect never lands: the live tree is exactly as the run started.
    assert not (repo / rel).exists()


# --- 4: fresh check failure ---------------------------------------------------------

def test_scenario_fresh_check_failure(tmp_path, monkeypatch):
    # The worker claims a clean PASS on an intact tree, but the suite fails in
    # the host's fresh Job the worker never touched.
    repo, cfg, calls, rc = _run(
        tmp_path, monkeypatch,
        fresh_result=(1, "FAILED tests/t_test.py::test_x - assert False"))
    assert rc == 1  # the exit equals the published verdict's rc
    dst = _published(repo)
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "FRESH-FAIL"
    assert dst["rc"] == 1
    assert any("FRESH-CHECK" in e for e in _published_failures(repo))


# --- 5: infrastructure failure ------------------------------------------------------

def test_scenario_infra_failure_fresh_unavailable(tmp_path, monkeypatch):
    # The fresh check cannot run at all: the verdict cannot be issued —
    # rc=16 ENV-FAIL, not a verdict (call the human).
    repo, cfg, calls, rc = _run(
        tmp_path, monkeypatch,
        fresh_result=(2, "EXEC_ERROR: fresh Job failed to start"))
    assert rc == 16
    dst = _published(repo)
    assert dst["probe_result"] == "ENV-FAIL"
    assert dst["rc"] == 16
    assert any("fresh check unavailable" in e for e in _published_failures(repo))


# --- 6: forged summary over a tampered tree ------------------------------------------

def test_scenario_forged_pass_over_tampered_tree(tmp_path, monkeypatch):
    # The classic forgery: the worker weakens an existing protected test
    # (its own suite now passes) and its payload claims a clean PASS. The
    # host recompute over the patched scratch sees the MODIFIED protected
    # file — the forged PASS does not survive.
    repo, cfg, calls, rc = _run(tmp_path, monkeypatch, patch_text=_WEAKEN_PATCH)
    assert rc == 1
    dst = _published(repo)
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert any("tests/t_test.py" in x for x in _published_failures(repo))
    assert "fresh" not in calls
    # The tampering stays in the scratch: the live test is untouched.
    assert "assert 1 == 1" in (repo / "tests" / "t_test.py").read_text(encoding="utf-8")


# --- 7: honest worker FAIL, fresh green ---------------------------------------------

def test_scenario_honest_fail_not_fabricated(tmp_path, monkeypatch):
    # The host's authority is exactly two checks, both downgrades: a green
    # fresh check over the final tree does NOT flip the worker's honest FAIL
    # into a PASS — the honest verdict is published unchanged.
    repo, cfg, calls, rc = _run(tmp_path, monkeypatch,
                                worker_summary=dict(HONEST_FAIL_WORKER))
    assert "fresh" in calls  # the fresh check is not gated on the worker's claims
    assert rc == 1  # the exit equals the published verdict's rc
    dst = _published(repo)
    dst.pop("patch_sha256")
    dst.pop("image_digest")
    dst.pop("acceptance")  # host stamp (G4), like the two above
    dst.pop("resource_peaks")  # host stamp (measurement), like the three above
    assert dst == dict(HONEST_FAIL_WORKER, rc=1)  # unchanged: no fabrication


# --- 8: no evidence payload block ----------------------------------------------------

def test_scenario_no_payload_publishes_nothing(tmp_path, monkeypatch):
    # The exactly-one rule: no nonce-matching block -> the run is treated as
    # aborted (status 'missing'), NO verdict is published, rc=17.
    repo, cfg, calls, rc = _run(tmp_path, monkeypatch, payload=False)
    assert rc == 17
    assert not (repo / "evidence" / "lbl" / "summary.json").exists()
    assert not (tmp_path / ".running").exists()  # the marker is cleaned up


# --- 9: declared new test keeps PASS ----------------------------------------------

def test_scenario_declared_new_test_keeps_pass(tmp_path, monkeypatch):
    # The declared exemption end-to-end (moved from test_stage3_tests_tree.py;
    # the host wiring — ticket declared paths reach the host check — is proven
    # here: the exemption only applies because host_launch_k8s parsed them).
    repo, cfg, calls, rc = _run(
        tmp_path, monkeypatch,
        ticket_text="test: tests/new_test.py\nrun.sh: exists\n",
        patch_text=_new_file_patch("tests/new_test.py",
                                   "def test_new():\n    pass"))
    assert rc == 0
    dst = _published(repo)
    dst.pop("patch_sha256")
    dst.pop("image_digest")
    dst.pop("acceptance")  # host stamp (G4), like the two above
    dst.pop("resource_peaks")  # host stamp (measurement), like the three above
    assert dst == CLEAN_WORKER  # no host override: the PASS stands
    assert "fresh" in calls  # the fresh check ran over an intact tree
    # the clean-path apply: the declared deliverable lands in the live tree
    assert (repo / "tests" / "new_test.py").is_file()


# --- 10: acceptance contract is host-stamped (G4) ---------------------------------

def test_scenario_acceptance_is_host_stamped(tmp_path, monkeypatch):
    # The published acceptance record comes from the HOST's parse of the
    # ticket, not from the worker's payload (the Pod is not its own judge,
    # same as patch_sha256/image_digest). The worker summary here carries no
    # acceptance key at all — the host stamps it from its own parse.
    repo, cfg, calls, rc = _run(
        tmp_path, monkeypatch,
        ticket_text="# scenario\n\naccept: tests/t_test.py\nreset: none\n")
    assert rc == 0
    dst = _published(repo)
    assert dst["acceptance"] == {"mode": "provided", "paths": ["tests/t_test.py"]}
    assert "fresh" in calls


# --- 11: the k8s path self-validates the ticket contract (B5) -----------------

def test_scenario_empty_declared_ticket_refused_before_cluster(tmp_path, monkeypatch):
    # B5 (review 2026-10-17): the cli gate was not mirrored here — the k8s
    # path accepted an empty-declared ticket with no `reset: none`, a ticket
    # whose invariant cannot be enforced. host_launch_k8s now refuses it
    # itself: rc=13 (ExitCode.TICKET, the same code the cli gate uses,
    # cli.py:198-203) EARLY-ABORT published, BEFORE any cluster call (the
    # machine never starts for an unsatisfiable contract).
    repo, cfg, calls, rc = _run(
        tmp_path, monkeypatch,
        ticket_text="# scenario\n\nno declared deliverables\n")
    assert rc == 13
    assert calls == []  # refused before any kubectl call
    dst = _published(repo)
    assert dst["probe_result"] == "EARLY-ABORT"
    assert dst["rc"] == 13
    assert any("reset: none" in x for x in _published_failures(repo))


# --- 12: identity mismatch before the live apply -> no published PASS (A5) ----

def test_scenario_identity_mismatch_before_live_apply_downgrades(tmp_path,
                                                                 monkeypatch):
    # A5 (review 2026-10-17): the identity re-check immediately before the
    # live apply failed — the old code logged a WARN and still published
    # rc=0/PASS with the patch UNAPPLIED. A claimed PASS whose patch never
    # landed is not a PASS: rc=16 ENV-FAIL, the published summary is
    # overwritten, and the declared deliverable does NOT land in the live
    # tree. patch_identity_ok runs exactly twice on the clean path (scratch
    # gate, live-apply gate) — the stub passes the first, fails the second.
    repo, cfg, args, calls = _k8s_scenario(
        tmp_path, monkeypatch,
        ticket_text="test: tests/new_test.py\nrun.sh: exists\n",
        patch_text=_new_file_patch("tests/new_test.py",
                                   "def test_new():\n    pass"))
    state = {"n": 0}

    def counting(path, sha):
        state["n"] += 1
        return state["n"] == 1
    monkeypatch.setattr(k8s, "patch_identity_ok", counting)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert state["n"] == 2  # both gates ran (the stub targets the second)
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    assert any("identity mismatch" in x for x in _published_failures(repo))
    # the patch did not land: the live tree is exactly as the run started
    assert not (repo / "tests" / "new_test.py").exists()


# --- 13: live git apply fails -> no published PASS (A5, natural failure) -----

def test_scenario_live_apply_failure_downgrades(tmp_path, monkeypatch):
    # A5 (review 2026-10-17), the other branch: the real `git apply` on the
    # live tree fails. Made natural: the fresh Job's stub writes the declared
    # file into the LIVE tree first (a foreign drift — the Pod never touches
    # the live tree; here it stands for any), so the real apply fails on
    # "already exists". Same downgrade: rc=16 ENV-FAIL, summary overwritten,
    # and the live tree keeps the FOREIGN content — the patch did not land.
    repo, cfg, args, calls = _k8s_scenario(
        tmp_path, monkeypatch,
        ticket_text="test: tests/new_test.py\nrun.sh: exists\n",
        patch_text=_new_file_patch("tests/new_test.py",
                                   "def test_new():\n    pass"))

    def rogue_fresh(*a, **k):
        calls.append("fresh")
        (repo / "tests" / "new_test.py").write_text(
            "# foreign content, not the patch\n", encoding="utf-8")
        return (0, "")
    monkeypatch.setattr(k8s, "_fresh_job", rogue_fresh)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    assert any("git apply" in x for x in _published_failures(repo))
    assert (repo / "tests" / "new_test.py").read_text(
        encoding="utf-8") == "# foreign content, not the patch\n"
