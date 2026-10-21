"""BL-4 — infrastructure classification of Pod deaths (host-side, 2026-10-16).

The gap: _wait_job_terminal reads only Job-level status.conditions — a
failed Job says 'Failed', not WHY. The Pod's own status says why:
terminated.reason == "OOMKilled" (cgroup OOM; measured 2026-10-16 under
gVisor: kubelet reports it honestly — the Pod-slice limit is enforced, the
overshoot is swap-absorbed until the swap is exhausted) or status.reason ==
"Evicted" (kubelet eviction). An infrastructure cause is rc=16 ENV-FAIL
(call the human), NOT a ticket defect: the worker path no longer reports a
generic 'missing' (rc=17), the fresh path no longer burns the 3 retries on
a FRESH-FAIL. A bare exit 137 with NO reason is NOT OOM — the Job's
activeDeadlineSeconds kill is also a SIGKILL. The cm_patch transport guard
adds only the fail-before-kubectl symmetry with the tree guard; the
EXEC_ERROR -> rc=16 classification already existed (proven in
test_scenarios_verdict.py scenario 5).

Tests (synthetic Pod JSON fixtures; no test reaches a real cluster):
  1  _pod_infra_cause: OOMKilled / Evicted classified; exit 137 without a
     reason, a plain test failure, no pod, kubectl error, bad JSON -> None
  2  _fresh_job: fresh Pod OOMKilled / Evicted -> EXEC_ERROR (the caller's
     rc=16 mapping is scenario 5's); a normal fresh failure keeps the old
     (rc, tail) path unchanged
  3  _fresh_job: the patch transport guard — a patch over TRANSPORT_MAX_B64
     fails closed BEFORE any kubectl call (symmetry with the tree guard)
  4  wiring (host_launch_k8s): worker Pod OOMKilled without payload ->
     rc=16 ENV-FAIL published with the cause named; a Pod exit 137 WITHOUT
     a reason keeps the 'missing' path (rc=17, nothing published)
  5  wiring: fresh Pod OOMKilled through the REAL _fresh_job in the mocked
     cluster cycle -> rc=16 ENV-FAIL, not FRESH-FAIL
  6  A1 (review 2026-10-17): the fresh path reads the Job-level
     DeadlineExceeded too (symmetry with the worker path) -> EXEC_ERROR ->
     rc=16, unit and end-to-end
  7  C3 host side: a fresh Job exiting with FRESH_APPLY_FAIL_RC (the Pod's
     own git apply failed before any test ran) -> EXEC_ERROR, not a tail

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_infra_cause.py -q
"""
import argparse
import json
import subprocess

from launcher import k8s, kube, preflight
from launcher.config import Config

CLEAN_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
                "probe_result": "CLEAN-FIRST", "turns": 1, "loop_trap": None}
FIXED_NONCE = "0123456789abcdef0123456789abcdef"
FAKE_IMAGE = "192.168.122.156:5000/stanok-machine@sha256:fake"

# Synthetic Pod fixtures — the shapes the kubelet actually reports (the
# 2026-10-16 probe: OOMKilled carried exitCode 128 with the reason set;
# a deadline kill is SIGKILL 137 with NO reason).
OOM_POD = {"status": {"phase": "Failed", "containerStatuses": [
    {"name": "worker", "state": {"terminated": {"exitCode": 128,
                                                "reason": "OOMKilled"}}}]}}
EVICTED_POD = {"status": {"phase": "Failed", "reason": "Evicted",
                          "message": "The node was low on resource: memory.",
                          "containerStatuses": [
                              {"state": {"terminated": {"exitCode": 137,
                                                       "reason": "Error"}}}]}}
DEADLINE_POD = {"status": {"phase": "Failed", "containerStatuses": [
    {"name": "worker", "state": {"terminated": {"exitCode": 137}}}]}}
TESTFAIL_POD = {"status": {"phase": "Failed", "containerStatuses": [
    {"name": "worker", "state": {"terminated": {"exitCode": 1,
                                                "reason": "Error"}}}]}}
# Job-level fixtures (deadline contract, external review 2026-10-16): the
# Pod shows a bare 137; the Job's Failed condition carries the honest reason.
DEADLINE_JOB = {"status": {"conditions": [
    {"type": "Failed", "status": "True", "reason": "DeadlineExceeded",
     "message": "Job was active longer than specified deadline"}]}}
OTHER_FAILED_JOB = {"status": {"conditions": [
    {"type": "Failed", "status": "True", "reason": "BackoffLimitExceeded"}]}}


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


# --- 1: _pod_infra_cause — the classification itself -----------------------------

def _stub_pod(monkeypatch, pod_json, rc=0):
    def fake(*a, **k):
        if rc != 0:
            return _FakeCompleted(rc, "", "pods not found")
        return _FakeCompleted(0, json.dumps(pod_json))
    monkeypatch.setattr(kube, "_kubectl", fake)


def test_oomkilled_reason_is_classified(monkeypatch):
    _stub_pod(monkeypatch, OOM_POD)
    assert k8s._pod_infra_cause("pod-x", "default") == "OOMKilled"


def test_evicted_status_reason_is_classified(monkeypatch):
    _stub_pod(monkeypatch, EVICTED_POD)
    assert k8s._pod_infra_cause("pod-x", "default") == "Evicted"


def test_bare_exit_137_is_not_oom(monkeypatch):
    # the Job's activeDeadlineSeconds kill is also a SIGKILL — without a
    # reason it must NOT be classified as OOM (it stays 'missing'/FRESH path).
    _stub_pod(monkeypatch, DEADLINE_POD)
    assert k8s._pod_infra_cause("pod-x", "default") is None


def test_plain_test_failure_is_not_infra(monkeypatch):
    _stub_pod(monkeypatch, TESTFAIL_POD)
    assert k8s._pod_infra_cause("pod-x", "default") is None


def test_fail_soft_is_none(monkeypatch):
    assert k8s._pod_infra_cause(None, "default") is None  # no pod
    _stub_pod(monkeypatch, OOM_POD, rc=1)
    assert k8s._pod_infra_cause("pod-x", "default") is None  # kubectl error
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: _FakeCompleted(0, "not json"))
    assert k8s._pod_infra_cause("pod-x", "default") is None  # unparseable
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: _FakeCompleted(0, "{}"))
    assert k8s._pod_infra_cause("pod-x", "default") is None  # no status


# --- 1b: _job_infra_cause — the Job-level deadline signal ------------------------

def _stub_job(monkeypatch, job_json, rc=0):
    def fake(*a, **k):
        if rc != 0:
            return _FakeCompleted(rc, "", "jobs not found")
        return _FakeCompleted(0, json.dumps(job_json))
    monkeypatch.setattr(kube, "_kubectl", fake)


def test_job_deadline_exceeded_condition_is_classified(monkeypatch):
    _stub_job(monkeypatch, DEADLINE_JOB)
    assert k8s._job_infra_cause("stanok-job-lbl", "default") == "DeadlineExceeded"


def test_other_failed_reason_is_not_deadline(monkeypatch):
    # BackoffLimitExceeded etc. stay the 'missing'/ticket path — only the
    # deadline reason is the Job-level infrastructure signal.
    _stub_job(monkeypatch, OTHER_FAILED_JOB)
    assert k8s._job_infra_cause("stanok-job-lbl", "default") is None
    _stub_job(monkeypatch, {"status": {"conditions": [
        {"type": "Complete", "status": "True"}]}})
    assert k8s._job_infra_cause("stanok-job-lbl", "default") is None


def test_job_infra_cause_fail_soft_is_none(monkeypatch):
    _stub_job(monkeypatch, DEADLINE_JOB, rc=1)
    assert k8s._job_infra_cause("stanok-job-lbl", "default") is None
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: _FakeCompleted(0, "not json"))
    assert k8s._job_infra_cause("stanok-job-lbl", "default") is None
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(0, "{}"))
    assert k8s._job_infra_cause("stanok-job-lbl", "default") is None


# --- 2: _fresh_job — infra cause -> EXEC_ERROR; normal failure unchanged ---------

def _fresh_env(tmp_path, monkeypatch, pod_json, job_rc_tail=None, job_json=None):
    cfg = Config(repo_root=str(tmp_path), log_dir=str(tmp_path / "logs"))
    patch_file = tmp_path / "changes.patch"
    patch_file.write_text("diff --git a/src/x.py b/src/x.py\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(kube, "_kubectl_checked",
                        lambda *a, **k: calls.append(a) or _FakeCompleted(0))
    monkeypatch.setattr(kube, "_create_manifest",
                        lambda text: calls.append(("manifest",)))
    monkeypatch.setattr(k8s, "_wait_job_terminal", lambda *a, **k: "failed")
    monkeypatch.setattr(k8s, "_pod_of_job", lambda *a, **k: "pod-x")

    def fake_kubectl(*a, **k):
        if a[:2] == ("get", "job") and job_json is not None:
            return _FakeCompleted(0, json.dumps(job_json))
        return _FakeCompleted(0, json.dumps(pod_json))
    monkeypatch.setattr(kube, "_kubectl", fake_kubectl)
    if job_rc_tail is not None:
        monkeypatch.setattr(k8s, "_job_rc_and_tail", lambda *a, **k: job_rc_tail)
    return cfg, patch_file, calls


def _call_fresh(cfg, patch_file):
    return k8s._fresh_job(cfg, "default", "stanok-fresh-lbl", "cm-tree",
                          "cm-patch", str(patch_file), 60, [], FAKE_IMAGE)


def test_fresh_pod_oom_returns_exec_error(tmp_path, monkeypatch):
    # (a2) the fresh path: OOMKilled -> EXEC_ERROR, the caller maps it to
    # rc=16 ENV-FAIL (scenario 5 proves the mapping) — not a FRESH-FAIL.
    cfg, patch_file, _ = _fresh_env(tmp_path, monkeypatch, OOM_POD)
    rc, tail = _call_fresh(cfg, patch_file)
    assert rc == 1
    assert tail.startswith("EXEC_ERROR:")
    assert "OOMKilled" in tail


def test_fresh_pod_evicted_returns_exec_error(tmp_path, monkeypatch):
    cfg, patch_file, _ = _fresh_env(tmp_path, monkeypatch, EVICTED_POD)
    rc, tail = _call_fresh(cfg, patch_file)
    assert rc == 1
    assert tail.startswith("EXEC_ERROR:")
    assert "Evicted" in tail


def test_fresh_normal_failure_path_unchanged(tmp_path, monkeypatch):
    # a test failure in the fresh Job stays a FRESH-FAIL with the tail —
    # the classification must not swallow it.
    cfg, patch_file, _ = _fresh_env(
        tmp_path, monkeypatch, TESTFAIL_POD,
        job_rc_tail=(1, "FAILED tests/t_test.py::test_x - assert False"))
    rc, tail = _call_fresh(cfg, patch_file)
    assert rc == 1
    assert not tail.startswith("EXEC_ERROR")
    assert "FAILED tests/t_test.py" in tail


def test_fresh_job_deadline_returns_exec_error(tmp_path, monkeypatch):
    # A1 (review 2026-10-17): the fresh Job was killed by its own
    # activeDeadlineSeconds — the Pod shows a bare 137 (_pod_infra_cause
    # refuses to guess), the Job condition says DeadlineExceeded. The worker
    # path already classifies this as infrastructure; the fresh path must
    # too: EXEC_ERROR (the caller maps to rc=16), not a FRESH-FAIL burning
    # the ticket's 3 retries on an infrastructure defect.
    cfg, patch_file, _ = _fresh_env(tmp_path, monkeypatch, DEADLINE_POD,
                                    job_json=DEADLINE_JOB)
    rc, tail = _call_fresh(cfg, patch_file)
    assert rc == 1
    assert tail.startswith("EXEC_ERROR:")
    assert "DeadlineExceeded" in tail


def test_fresh_apply_failure_maps_to_exec_error(tmp_path, monkeypatch):
    # C3 host side: the Pod-side apply guard (fresh-job.yaml.tmpl) exits
    # with FRESH_APPLY_FAIL_RC before any test ran. The host already applied
    # the identical verified bytes to the scratch tree — the same patch
    # failing on the same tree is a Pod anomaly (infrastructure, rc=16),
    # never a test result.
    cfg, patch_file, _ = _fresh_env(
        tmp_path, monkeypatch, TESTFAIL_POD,
        job_rc_tail=(k8s.FRESH_APPLY_FAIL_RC,
                     "FRESH: git apply of changes.patch failed (rc=1)"))
    rc, tail = _call_fresh(cfg, patch_file)
    assert rc == 1
    assert tail.startswith("EXEC_ERROR:")
    assert "git apply" in tail


# --- 3: the cm_patch transport guard (symmetry with the tree guard) --------------

def test_patch_guard_fails_before_any_kubectl(tmp_path, monkeypatch):
    # (b) a patch over the ConfigMap limit fails closed BEFORE the cluster
    # call; the classification (EXEC_ERROR -> rc=16) is unchanged.
    cfg, patch_file, calls = _fresh_env(tmp_path, monkeypatch, TESTFAIL_POD)
    patch_file.write_bytes(b"x" * (k8s.TRANSPORT_MAX_B64 + 1))
    rc, tail = _call_fresh(cfg, patch_file)
    assert rc == 1
    assert tail.startswith("EXEC_ERROR:")
    assert "ConfigMap limit" in tail
    assert calls == []  # no kubectl call was made at all


def test_patch_under_the_limit_reaches_the_cluster(tmp_path, monkeypatch):
    # the guard is a size check, not a ban: an under-limit patch still runs
    # the create (regression against an over-broad guard).
    cfg, patch_file, calls = _fresh_env(tmp_path, monkeypatch, TESTFAIL_POD,
                                        job_rc_tail=(1, "tail"))
    rc, tail = _call_fresh(cfg, patch_file)
    assert ("create", "configmap", "cm-patch", "-n", "default",
            f"--from-file=changes.patch={patch_file}") in calls


# --- 4/5: wiring through host_launch_k8s (mocked cluster cycle) ------------------

def _repo(tmp_path):
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


def _scenario(tmp_path, monkeypatch, *, payload=True, pod_json=None,
              real_fresh=False, job_json=None):
    """host_launch_k8s with the cluster cycle mocked (the
    test_scenarios_verdict harness shape) plus: pod_json — what `get pod -o
    json` answers (None -> not found); job_json — what `get job -o json`
    answers (None -> empty status); real_fresh — the REAL _fresh_job runs
    against the mocked cluster (worker Job completes, fresh Job fails)."""
    repo, cfg = _repo(tmp_path)
    ticket = tmp_path / "ticket.md"
    # B5 (review 2026-10-17): host_launch_k8s now self-validates the ticket
    # contract — an empty-declared ticket is only valid with `reset: none`.
    ticket.write_text("# scenario\n\nreset: none\n", encoding="utf-8")
    args = argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket), local_retries=0, extra=[])
    calls = []

    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(preflight, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "_image_ref", lambda cfg: (FAKE_IMAGE, None))
    monkeypatch.setattr(k8s, "new_nonce", lambda: FIXED_NONCE)
    monkeypatch.setattr(k8s, "_install_signal_handlers", lambda rs: None)

    def fake_kubectl(*a, **k):
        calls.append(a[0] if a else "")
        if a[:2] == ("get", "pod"):
            if pod_json is None:
                return _FakeCompleted(1, "", "pods not found")
            return _FakeCompleted(0, json.dumps(pod_json))
        if a[:2] == ("get", "job") and job_json is not None:
            return _FakeCompleted(0, json.dumps(job_json))
        return _FakeCompleted(0)
    monkeypatch.setattr(kube, "_kubectl", fake_kubectl)
    monkeypatch.setattr(k8s, "_pod_of_job", lambda *a, **k: "pod-x")

    def fake_stream(pod, ns, path, deadline):
        if not payload:
            text = "worker stdout without any evidence block\n"
        else:
            files = {"summary.json": json.dumps(CLEAN_WORKER).encode("utf-8")}
            text = (k8s.begin_marker(FIXED_NONCE) + "\n"
                    + k8s.build_payload(files) + "\n"
                    + k8s.end_marker(FIXED_NONCE) + "\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True  # A2: the new contract — a successful stream reports True
    monkeypatch.setattr(k8s, "_stream_pod_logs", fake_stream)

    if real_fresh:
        monkeypatch.setattr(
            k8s, "_wait_job_terminal",
            lambda name, *a, **k: ("failed" if name.startswith("stanok-fresh")
                                   else "complete"))
    else:
        monkeypatch.setattr(k8s, "_wait_job_terminal", lambda *a, **k: "complete")
        monkeypatch.setattr(k8s, "_fresh_job",
                            lambda *a, **k: calls.append("fresh") or (0, ""))
    monkeypatch.setattr(k8s, "_pod_image_id", lambda pod, ns: FAKE_IMAGE)
    return repo, cfg, args, calls


def _published(repo):
    return json.loads((repo / "evidence" / "lbl" / "summary.json")
                      .read_text(encoding="utf-8"))


def _published_failures(repo):
    p = repo / "evidence" / "lbl" / "failures.log"
    if not p.is_file():
        return []
    return [line for line in p.read_text(encoding="utf-8").splitlines() if line]


def test_worker_pod_oom_publishes_env_fail(tmp_path, monkeypatch):
    # (a1) the worker Pod died of a cgroup OOM with no payload — the run is
    # an infrastructure defect (rc=16, cause named), not a generic 'missing'.
    repo, cfg, args, calls = _scenario(tmp_path, monkeypatch, payload=False,
                                       pod_json=OOM_POD)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    assert any("OOMKilled" in x for x in _published_failures(repo))


def test_worker_pod_bare_137_keeps_missing_path(tmp_path, monkeypatch):
    # regression: a bare 137 with NO reason is NOT OOM, and without a
    # Job-level DeadlineExceeded condition the run stays the 'missing'
    # abort (rc=17, nothing published) — neither channel may be guessed.
    repo, cfg, args, calls = _scenario(tmp_path, monkeypatch, payload=False,
                                       pod_json=DEADLINE_POD)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert rc == 17
    assert not (repo / "evidence" / "lbl" / "summary.json").exists()


def test_worker_job_deadline_exceeded_publishes_env_fail(tmp_path, monkeypatch):
    # Deadline contract (external review 2026-10-16): the session outlived
    # the Job's activeDeadlineSeconds — the Job condition says
    # DeadlineExceeded (the Pod shows only a bare 137): rc=16 ENV-FAIL with
    # the cause and the knobs named, not a generic 'missing'.
    repo, cfg, args, calls = _scenario(tmp_path, monkeypatch, payload=False,
                                       pod_json=DEADLINE_POD,
                                       job_json=DEADLINE_JOB)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    failures = _published_failures(repo)
    assert any("DeadlineExceeded" in x for x in failures)


def test_fresh_pod_oom_maps_to_env_fail(tmp_path, monkeypatch):
    # (a2) end-to-end: the worker payload is clean, the contract is intact,
    # the fresh Pod is OOM-killed — the run is rc=16 ENV-FAIL (fresh check
    # unavailable), NOT a FRESH-FAIL burning the ticket's retries.
    repo, cfg, args, calls = _scenario(tmp_path, monkeypatch, real_fresh=True,
                                       pod_json=OOM_POD)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    failures = _published_failures(repo)
    assert any("fresh check unavailable" in x for x in failures)
    assert any("OOMKilled" in x for x in failures)


def test_fresh_job_deadline_maps_to_env_fail(tmp_path, monkeypatch):
    # A1 (review 2026-10-17) end-to-end: the worker payload is clean, the
    # fresh Job was killed by its own activeDeadlineSeconds (Pod: bare 137,
    # Job condition: DeadlineExceeded) -> rc=16 ENV-FAIL "fresh check
    # unavailable" with the cause named — not a FRESH-FAIL burning the
    # ticket's 3 retries.
    repo, cfg, args, calls = _scenario(tmp_path, monkeypatch, real_fresh=True,
                                       pod_json=DEADLINE_POD,
                                       job_json=DEADLINE_JOB)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert rc == 16
    dst = _published(repo)
    assert dst["rc"] == 16
    assert dst["probe_result"] == "ENV-FAIL"
    failures = _published_failures(repo)
    assert any("fresh check unavailable" in x for x in failures)
    assert any("DeadlineExceeded" in x for x in failures)
