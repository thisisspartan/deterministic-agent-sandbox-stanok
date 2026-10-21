"""Stage 3 T3-1 — host-side contract snapshot BEFORE the worker starts
(rewritten onto the k8s runtime by CC-258 — the Docker path is removed).

Trust boundary (operator review 2026-10-09, SPEC-VERDICT-INTEGRITY §1): the
verdict must not depend on files the worker can rewrite. The host snapshots
the protected files (tests/**, scripts/run.sh, scripts/stacks/*.toml —
verify._protected_files, the one source, CC-136) before the worker Job
starts and keeps the snapshot in the HOST PROCESS MEMORY only: anything the
Pod can reach is outside the trust boundary. T3-2 recomputes after the run
ends and compares (the k8s form: over the patched scratch tree,
test_k8s_contract_scratch.py).

Tests:
  1  host_launch_k8s computes the snapshot BEFORE the first cluster call
     that carries the worker's context (ConfigMap/Job create) — call order
     via mocks; the boundary is the transport of the tree, not the verdict
     phase (the old boundary was the docker argv construction)
  2  the snapshot covers the protected files with sha256 digests (unit)
  3  the snapshot is memory only: contract_snapshot writes nothing to disk
  4  a protected-file change after the snapshot is detectable by recompute
     (the guard T3-2 builds on)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_host_snapshot.py -q
"""
import argparse
import hashlib
import os

from launcher import k8s, kube, payload, preflight, verify
from launcher.config import Config


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    pass\n",
                                               encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (repo / "scripts" / "stacks").mkdir()
    (repo / "scripts" / "stacks" / "py.toml").write_text('ext = "py"\n',
                                                          encoding="utf-8")
    logdir = tmp_path / "logs"
    logdir.mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(logdir))


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


# --- 1: the snapshot precedes the cluster calls ----------------------------------

def test_snapshot_computed_before_cluster_calls(tmp_path, monkeypatch):
    repo, cfg = _repo(tmp_path)
    ticket = tmp_path / "ticket.md"
    ticket.write_text("test: tests/x_test.py\nrun.sh: exists\n", encoding="utf-8")
    args = argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket), local_retries=0, extra=[])
    calls = []

    def spy_snapshot(c):
        calls.append("snapshot")
        return verify._tests_manifest(c)

    monkeypatch.setattr(verify, "contract_snapshot", spy_snapshot)
    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(preflight, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "_image_ref", lambda cfg: (
        "192.168.122.156:5000/stanok-machine@sha256:fake", None))
    monkeypatch.setattr(payload, "pack_tree", lambda root: "x")
    monkeypatch.setattr(payload, "transport_ok", lambda blob: True)

    def stop(*a, **k):
        calls.append(a[0])
        return _FakeCompleted(1, stderr="stop-here")  # -> _kubectl_checked raises
    monkeypatch.setattr(kube, "_kubectl", stop)

    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert rc == 16  # the failed cluster call -> infra path
    assert "snapshot" in calls and "create" in calls
    # The boundary is the transport of the tree: a snapshot taken after the
    # first create (the ConfigMap already carries the worker's context) is
    # NOT "before the worker starts" — the mutant that moves it there dies.
    assert calls.index("snapshot") < calls.index("create")


# --- 2: the snapshot is the protected-files manifest ------------------------------

def test_snapshot_covers_protected_files(tmp_path):
    repo, cfg = _repo(tmp_path)
    snap = verify.contract_snapshot(cfg)
    assert snap["tests/t_test.py"] == hashlib.sha256(
        b"def test_x():\n    pass\n").hexdigest()
    assert snap["scripts/run.sh"] == hashlib.sha256(b"#!/bin/bash\n").hexdigest()
    assert snap["scripts/stacks/py.toml"] == hashlib.sha256(
        b'ext = "py"\n').hexdigest()


# --- 3: memory only — nothing lands on disk ---------------------------------------

def test_snapshot_writes_nothing_to_disk(tmp_path):
    repo, cfg = _repo(tmp_path)
    verify.contract_snapshot(cfg)
    # A file in LOG_DIR would sit in the host's run zone and could be forged
    # after the fact — the snapshot exists only in host process memory.
    assert os.listdir(cfg.log_dir) == []
    assert not (repo / "evidence").exists()


# --- 4: a post-snapshot change is detectable (T3-2 guard) ------------------------

def test_change_after_snapshot_is_detectable(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    (repo / "tests" / "t_test.py").write_text("tampered after snapshot\n",
                                              encoding="utf-8")
    after = verify.contract_snapshot(cfg)
    assert after["tests/t_test.py"] != before["tests/t_test.py"]
