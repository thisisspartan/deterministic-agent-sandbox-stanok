"""B4 (external review 2026-10-17) — the live-apply tree-identity guard.

The verdict is computed against the TRANSPORTED tree (`git archive HEAD` at
snapshot time) + patch; the patch then lands on the LIVE tree. If the live
tree drifted during the run (HEAD moved, or uncommitted changes appeared —
something outside the run touched it), the apply target is no longer the
tree the verdict was computed against. k8s._live_tree_drift re-checks,
immediately before the live apply and after the third identity check:
HEAD == STANOK_START_COMMIT (the commit cli captured before launch) and
porcelain clean; fail closed (a git error is drift, an unset
STANOK_START_COMMIT is drift). A drift downgrades the claimed PASS to
rc=16 ENV-FAIL via write_env_fail_summary (same pattern as the A5
identity/apply branches) and the patch is NOT applied.

Operator requirements (decision 2026-10-17, variant 1, STATUS.md):
  (1) the message names the patch path from the `patch_file` variable —
      the test verifies the path BY SUBSTANCE: the path in the message is
      the real file, its bytes are the patch;
  (2) the phrase that the patch is temporary and lives under /tmp is part
      of the message (LOG_DIR default /tmp/stanok-logs, config.py:83);
  (3) path + phrase in BOTH guard branches (HEAD and porcelain);
  (4) nothing is copied or deleted; the text lives in failures.log —
      summary.json stays typed (CC-237: free text never enters it,
      summary.py:338-340), so the substance check runs against
      failures.log and summary.json is checked for the typed fields only.

Cases: HEAD moved during the run; tree dirtied during the run; clean tree
passes the guard and the deliverable lands; unset STANOK_START_COMMIT;
git apply is NOT called when the guard fires; the message names the real
patch file in both branches; a git call that RAISES in the guard is
drift too (fail closed — the guard's own docstring; B1a review
2026-10-17, finding 1).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_head_drift.py -q
"""
import argparse
import json
import os
import subprocess

import pytest

from launcher import k8s, kube, lifecycle, payload, preflight
from launcher.config import Config

CLEAN_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
                "probe_result": "CLEAN-FIRST", "turns": 1, "loop_trap": None}

FIXED_NONCE = "0123456789abcdef0123456789abcdef"
FAKE_IMAGE = "192.168.122.156:5000/stanok-machine@sha256:fake"

NEW_TEST_PATCH = (
    "diff --git a/tests/new_test.py b/tests/new_test.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/tests/new_test.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def test_new():\n"
    "+    pass\n")

TICKET = "test: tests/new_test.py\nrun.sh: exists\n"


def _repo(tmp_path):
    """Git fixture: mirrors the real repo where the guard matters — a
    committed clean tree and evidence/ gitignored (.gitignore:2), so a
    published verdict does not dirty the tree the guard inspects."""
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    assert 1 == 1\n",
                                               encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    (repo / ".gitignore").write_text("evidence/\n", encoding="utf-8")
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
    p = repo / "evidence" / "lbl" / "failures.log"
    if not p.is_file():
        return []
    return [line for line in p.read_text(encoding="utf-8").splitlines() if line]


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _scenario(tmp_path, monkeypatch, fresh_hook=None, export_start_commit=True):
    """host_launch_k8s with the cluster cycle mocked (same shape as
    test_scenarios_verdict._k8s_scenario): a declared new-test ticket and a
    patch that WOULD land, fresh green — the run reaches the live-apply
    branch. fresh_hook runs inside the mocked fresh Job: it is the stand-in
    for "something outside the run touched the live tree mid-run" (the Pod
    itself never touches it). The fixture exports STANOK_START_COMMIT like
    the real cli (cli.py:627-639); export_start_commit=False simulates a
    launch where the capture never happened."""
    repo, cfg = _repo(tmp_path)
    if export_start_commit:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
        monkeypatch.setenv("STANOK_START_COMMIT", head)
    else:
        monkeypatch.delenv("STANOK_START_COMMIT", raising=False)
    ticket = tmp_path / "ticket.md"
    ticket.write_text(TICKET, encoding="utf-8")
    args = argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket), local_retries=0, extra=[])
    calls = []

    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(preflight, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "_image_ref", lambda cfg: (FAKE_IMAGE, None))
    monkeypatch.setattr(payload, "new_nonce", lambda: FIXED_NONCE)
    monkeypatch.setattr(k8s, "_install_signal_handlers", lambda rs: None)

    def fake_kubectl(*a, **k):
        calls.append(a[0] if a else "")
        return _FakeCompleted(0)
    monkeypatch.setattr(kube, "_kubectl", fake_kubectl)
    monkeypatch.setattr(lifecycle, "_pod_of_job", lambda *a, **k: "pod-x")

    def fake_stream(pod, ns, path, deadline):
        files = {"summary.json": json.dumps(CLEAN_WORKER).encode("utf-8"),
                 "changes.patch": NEW_TEST_PATCH.encode("utf-8")}
        text = (payload.begin_marker(FIXED_NONCE) + "\n"
                + payload.build_payload(files) + "\n"
                + payload.end_marker(FIXED_NONCE) + "\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    monkeypatch.setattr(lifecycle, "_stream_pod_logs", fake_stream)
    monkeypatch.setattr(lifecycle, "_wait_job_terminal", lambda *a, **k: "complete")
    monkeypatch.setattr(lifecycle, "_pod_image_id", lambda pod, ns: FAKE_IMAGE)

    def fake_fresh(*a, **k):
        calls.append("fresh")
        if fresh_hook is not None:
            fresh_hook()
        return (0, "")
    monkeypatch.setattr(k8s, "_fresh_job", fake_fresh)

    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    return repo, cfg, rc


def _moved_head(tmp_path):
    """Foreign commit during the run: HEAD moves, tree stays clean — the
    guard's HEAD branch."""
    def hook():
        (tmp_path / "repo" / "src" / "foreign.py").write_text("X = 1\n",
                                                               encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path / "repo"), "add", "-A"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path / "repo"), "commit",
                        "-qm", "foreign"], check=True, capture_output=True)
    return hook


def _dirtied_tree(tmp_path):
    """Foreign uncommitted file during the run: HEAD unchanged, porcelain
    non-empty — the guard's dirty branch."""
    def hook():
        (tmp_path / "repo" / "src" / "foreign.py").write_text("X = 1\n",
                                                               encoding="utf-8")
    return hook


# --- 1: HEAD moved during the run -> ENV-FAIL, patch not applied ---------------

def test_head_moved_during_run_downgrades(tmp_path, monkeypatch):
    repo, cfg, rc = _scenario(tmp_path, monkeypatch, fresh_hook=_moved_head(tmp_path))
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    assert any("the tree moved since the run began" in x
               for x in _published_failures(repo))
    # the patch did not land: the live tree keeps only the foreign content
    assert not (repo / "tests" / "new_test.py").exists()
    assert (repo / "src" / "foreign.py").is_file()


# --- 2: live tree dirtied during the run -> ENV-FAIL, patch not applied --------

def test_dirty_live_tree_during_run_downgrades(tmp_path, monkeypatch):
    repo, cfg, rc = _scenario(tmp_path, monkeypatch, fresh_hook=_dirtied_tree(tmp_path))
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    assert any("uncommitted changes" in x for x in _published_failures(repo))
    assert not (repo / "tests" / "new_test.py").exists()


# --- 3: clean tree passes the guard -> the deliverable lands (no false positive)

def test_clean_tree_passes_guard_and_apply_lands(tmp_path, monkeypatch):
    repo, cfg, rc = _scenario(tmp_path, monkeypatch)
    assert rc == 0
    assert (repo / "tests" / "new_test.py").is_file()
    dst = _published(repo)
    assert dst["rc"] == 0
    assert dst["verifier"] == "PASS"


# --- 4: unset STANOK_START_COMMIT -> drift (fail closed: unknowable start) -----

def test_unset_start_commit_downgrades(tmp_path, monkeypatch):
    # The start commit is unknowable -> the guard cannot prove the tree
    # unchanged -> drift, fail closed (the real cli always captures it,
    # cli.py:627-639 — this is the defensive branch).
    repo, cfg, rc = _scenario(tmp_path, monkeypatch, export_start_commit=False)
    assert rc == 16
    assert any("STANOK_START_COMMIT is unset" in x
               for x in _published_failures(repo))
    assert not (repo / "tests" / "new_test.py").exists()


# --- 5: when the guard fires, `git apply` is never called -----------------------

def test_guard_fires_before_git_apply_is_called(tmp_path, monkeypatch):
    real_run = subprocess.run
    seen = []

    def recorder(cmd, *a, **k):
        seen.append(([str(c) for c in cmd], k.get("cwd")))
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(k8s.subprocess, "run", recorder)
    repo, cfg, rc = _scenario(tmp_path, monkeypatch, fresh_hook=_dirtied_tree(tmp_path))
    assert rc == 16
    # The scratch apply (apply_patch_scratch, cwd=scratch dir) is legitimate
    # and expected; what must NOT happen is the LIVE apply (cwd=repo_root).
    live_applies = [c for c, cwd in seen
                    if c[:2] == ["git", "apply"] and cwd == str(repo)]
    assert live_applies == []  # the guard rejected before the apply call
    assert not (repo / "tests" / "new_test.py").exists()


# --- 6: the message names the REAL patch file, both branches (substance) -------

@pytest.mark.parametrize("branch,hook", [
    ("head", _moved_head), ("porcelain", _dirtied_tree)])
def test_message_names_the_real_patch_file(tmp_path, monkeypatch, branch, hook):
    repo, cfg, rc = _scenario(tmp_path, monkeypatch, fresh_hook=hook(tmp_path))
    assert rc == 16
    # summary.json is TYPED (CC-237): the free text never enters it — the
    # substance check runs against failures.log (summary.py:338-340).
    dst = _published(repo)
    assert dst["rc"] == 16
    assert "error" not in dst
    msg = next(l for l in _published_failures(repo) if "retained at " in l)
    # the path in the message, extracted by substance — not a substring check
    path = msg.split("retained at ", 1)[1].split(" (temporary", 1)[0]
    expected = os.path.join(cfg.label_paths("lbl")[1], "changes.patch")
    assert path == expected  # exactly what the `patch_file` variable holds
    with open(path, "rb") as f:
        assert f.read() == NEW_TEST_PATCH.encode("utf-8")  # the real patch
    # the temporary-by-design phrase is part of the message (operator req.)
    assert "(temporary, lives under /tmp)" in msg
    # nothing was copied: the patch lives ONLY in live_dir, not in evidence/
    assert not (repo / "evidence" / "lbl" / "changes.patch").exists()


# --- 7: a git call that RAISES in the guard is drift (fail closed) -------------

def test_raising_git_call_in_guard_downgrades(tmp_path, monkeypatch):
    # B1a review 2026-10-17, finding 1: the guard's docstring promises
    # "a git error counts as drift (unknown state)" — that must include a
    # call that RAISES (OSError / SubprocessError), not only a non-zero
    # rc. Without the try/except the exception would propagate AFTER the
    # PASS was published (k8s.py, _publish_evidence precedes the guard)
    # and the run would exit unaligned. Same fail-closed shape as
    # gates.dirty_tree_gate (gates.py:43-52) and cli._capture_start_commit
    # (cli.py:635-644).
    real_run = subprocess.run

    def raiser(cmd, *a, **k):
        # Only the guard's own call (exact argv, no -C): the fixture's
        # start-commit export and the git setup use "-C" argvs.
        if [str(c) for c in cmd] == ["git", "rev-parse", "HEAD"]:
            raise OSError("simulated git failure")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(k8s.subprocess, "run", raiser)
    repo, cfg, rc = _scenario(tmp_path, monkeypatch)
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    assert any("git rev-parse HEAD raised" in x
               for x in _published_failures(repo))
    assert not (repo / "tests" / "new_test.py").exists()
