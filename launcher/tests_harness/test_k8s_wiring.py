"""CC-258 (Docker runtime removed) — the runtime dispatch.

launch.sh keeps its contract (`run <ticket> <label> --follow`, status/wait/
stop unchanged); k8s is the ONLY runtime: main() dispatches inline (an
in-container / STANOK_NO_SANDBOX run IS the runtime/test mode; a host run
reaches k8s.host_launch_k8s), and an explicit STANOK_RUNTIME=docker is NOT
silently mapped to k8s — main() refuses the launch with ENV-FAIL ("docker
runtime removed"). (P4 2026-10-13: the former cli._runtime_mode constant and
its self-confirming test were removed — the refusal branch is covered by
test 3 below, which drives main() itself.)
Tests:
  2  the k8s host driver exists with the entry the dispatcher calls
  3  main() with STANOK_RUNTIME=docker -> rc=16 ENV-FAIL with the refusal
     text published; the k8s driver is never reached
 CC-232 (pre-flight doctor gate):
  6  _cluster_env: KUBECONFIG fallback to ~/.kube/config (operator host)
  7  _preflight_cluster: node-Ready and manifest-test branches
  8  host_launch_k8s: gate aborts (rc=16) BEFORE any cluster call; when the
     gate passes, the cluster calls follow it (order proven)
 P0 cleanup ownership (operator 2026-10-11):
  9  no test reaches a real cluster: the common kubectl choke point _kubectl
     is mocked, the direct subprocess.run points are a tripwire; the finally
     deletes ONLY resources whose creation by this run is proven (create,
     not apply) — a foreign object with a colliding name is never deleted
 Image provenance (operator plan 2026-10-12):
  10 _pod_image_id: reads the Pod's own containerStatuses.imageID (the
     runtime's record of the image the Job ran); accepts both runtime forms
     (docker bare "sha256:…", containerd "<repo>@sha256:…"); fail-soft -> None
 Image delivery (operator 2026-10-12): the two gate-passing wiring tests mock
     _image_ref (the docker inspect point is not a cluster call) — the
     delivery logic itself lives in test_k8s_image_delivery.py
 Unified launch preflight (operator spec 2026-10-12; wave A portion 3): the
     gate is now the unified preflight._preflight (disk/image/Opik/cluster/
     RuntimeClass/dangling) —
     the wiring tests mock it; the check logic itself lives in
     test_k8s_preflight.py, the _preflight_cluster branches stay tested here
 Verdict cross-check (external review 2026-10-16): the payload carries
     internal_rc.txt (the in-Pod session's own exit code, pod_runner.py);
     cli.py writes summary.json's "rc" and returns the same value, so a
     mismatch between the two channels is verdict-substitution — rc=16
     infrastructure defect, the worker verdict is never published. Absent
     (an image predating the contract) -> no check. The pod_runner side is
     tested in test_k8s_manifests.py

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_wiring.py -q
"""
import argparse
import json
import os

from launcher import cli, k8s, kube, patchgate, preflight
from launcher.config import Config


def test_host_driver_entry_exists():
    assert callable(k8s.host_launch_k8s)


def test_docker_runtime_env_is_refused(tmp_path, monkeypatch):
    # CC-258: STANOK_RUNTIME=docker is NOT silently mapped to k8s — main()
    # stops the launch with ENV-FAIL and the text "docker runtime removed".
    repo, cfg = _k8s_repo(tmp_path)
    args = _k8s_args(tmp_path)
    args.cmd = "run"
    args.follow = False
    monkeypatch.setenv("STANOK_RUNTIME", "docker")
    monkeypatch.delenv("STANOK_IN_CONTAINER", raising=False)
    monkeypatch.delenv("STANOK_NO_SANDBOX", raising=False)
    monkeypatch.delenv("STANOK_LOCK_KEY", raising=False)
    monkeypatch.setattr(cli.Config, "from_env", classmethod(lambda cls: cfg))

    class _StubParser:
        def parse_args(self):
            return args
    monkeypatch.setattr(cli, "_build_parser", lambda cfg: _StubParser())
    monkeypatch.setattr(cli, "_capture_start_commit", lambda cfg: None)
    # None, not a path: main() ASSIGNS
    # os.environ["STANOK_LOCK_KEY"] when _lock_key returns a key, and
    # monkeypatch cannot undo production-code assignments — a real path here
    # would leak into the pytest process and poison later _launch subprocesses
    # (test_worktree: wrong lock file -> rc=20 instead of 21). The lock branch
    # is not reached in this refusal test (no IN_CONTAINER/NO_SANDBOX).
    monkeypatch.setattr(cli, "_lock_key", lambda cfg: None)
    monkeypatch.setattr(cli, "_launch_gates", lambda cfg, args: None)

    def no_dispatch(*a, **k):
        raise AssertionError("STANOK_RUNTIME=docker must not reach the k8s driver")
    monkeypatch.setattr(k8s, "host_launch_k8s", no_dispatch)

    rc = cli.main()
    assert rc == 16  # ENV-FAIL: an infrastructure refusal, not a ticket defect
    with open(os.path.join(cfg.summary_dir("lbl"), "summary.json"),
              encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["rc"] == 16
    with open(os.path.join(cfg.summary_dir("lbl"), "failures.log"),
              encoding="utf-8") as f:
        assert "docker runtime removed" in f.read()


# --- 6: CC-232 _cluster_env (kubectl config fallback, operator host) ---------------

def test_cluster_env_falls_back_to_user_kubeconfig(tmp_path, monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    kc = tmp_path / ".kube" / "config"
    kc.parent.mkdir()
    kc.write_text("x", encoding="utf-8")
    assert kube._cluster_env()["KUBECONFIG"] == str(kc)
    # an explicit KUBECONFIG is never overridden
    monkeypatch.setenv("KUBECONFIG", "/somewhere/else")
    assert kube._cluster_env()["KUBECONFIG"] == "/somewhere/else"


def test_cluster_env_no_fallback_without_kubeconfig(tmp_path, monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no .kube/config there
    assert "KUBECONFIG" not in kube._cluster_env()


def test_stream_pod_logs_uses_cluster_env(tmp_path, monkeypatch):
    # incident cc233: the log stream called kubectl WITHOUT the config
    # resolution — it died on the non-readable /etc/rancher/k3s/k3s.yaml
    # fallback while every other kubectl call worked.
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    kc = tmp_path / ".kube" / "config"
    kc.parent.mkdir()
    kc.write_text("x", encoding="utf-8")
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        captured["env"] = kw.get("env")
        return _FakeCompleted(0)
    monkeypatch.setattr(k8s.subprocess, "run", fake_run)
    k8s._stream_pod_logs("pod-x", "default", str(tmp_path / "out.log"), 5)
    assert "logs" in captured["argv"]
    assert captured["env"] is not None
    assert captured["env"]["KUBECONFIG"] == str(kc)


# --- 7: CC-232 _preflight_cluster branches (no real cluster) ----------------------

class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _fake_cluster(monkeypatch, *, nodes_rc=0,
                  nodes_out="hermes   Ready   control-plane   1d   v1.36\n",
                  pytest_rc=0):
    seen = []

    def fake_run(argv, **kw):
        if "kubectl" in argv[0]:
            seen.append("nodes")
            return _FakeCompleted(nodes_rc, nodes_out,
                                  "" if nodes_rc == 0 else "connection refused")
        seen.append("pytest")
        return _FakeCompleted(pytest_rc,
                              "" if pytest_rc == 0 else "1 failed in 0.4s")
    monkeypatch.setattr(k8s.subprocess, "run", fake_run)
    return seen


def test_preflight_cluster_ok_is_none(tmp_path, monkeypatch):
    seen = _fake_cluster(monkeypatch)
    cfg = Config(repo_root=str(tmp_path), log_dir=str(tmp_path / "logs"))
    assert preflight._preflight_cluster(cfg) is None
    assert seen == ["nodes", "pytest"]  # both checks ran


def test_preflight_cluster_unreachable_is_reason(monkeypatch):
    _fake_cluster(monkeypatch, nodes_rc=1)
    cfg = Config(repo_root="/tmp", log_dir="/tmp")
    reason = preflight._preflight_cluster(cfg)
    assert reason and "cluster unreachable" in reason


def test_preflight_cluster_not_ready_node_is_reason(monkeypatch):
    _fake_cluster(monkeypatch, nodes_out="hermes   NotReady   control-plane\n")
    cfg = Config(repo_root="/tmp", log_dir="/tmp")
    reason = preflight._preflight_cluster(cfg)
    assert reason and "not Ready" in reason


def test_preflight_cluster_manifest_drift_is_reason(monkeypatch):
    _fake_cluster(monkeypatch, pytest_rc=1)
    cfg = Config(repo_root="/tmp", log_dir="/tmp")
    reason = preflight._preflight_cluster(cfg)
    assert reason and "manifest contract tests failed" in reason


# --- 8: CC-232 gate wiring in host_launch_k8s (order + fail-closed) ---------------

def _k8s_repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(tmp_path / "logs"))


def _k8s_args(tmp_path):
    ticket = tmp_path / "ticket.md"
    ticket.write_text("test: tests/x_test.py\nrun.sh: exists\n", encoding="utf-8")
    return argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket), local_retries=0, extra=[])


def _no_real_cluster_calls(monkeypatch):
    """P0 (operator 2026-10-11): a test must never reach a real cluster.
    The two direct subprocess.run points (preflight._preflight_cluster,
    k8s._stream_pod_logs) are a tripwire: if any code path bypasses the mocked
    _kubectl choke point, the test fails loudly instead of touching the
    cluster."""
    def guard(*a, **k):
        raise AssertionError(f"real cluster call from test: {a[:3]}")
    monkeypatch.setattr(k8s.subprocess, "run", guard)


def test_gate_aborts_before_any_cluster_call(tmp_path, monkeypatch):
    repo, cfg = _k8s_repo(tmp_path)
    args = _k8s_args(tmp_path)
    calls = []
    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(preflight, "_preflight",
                        lambda cfg: "cluster unreachable: mock")
    _no_real_cluster_calls(monkeypatch)
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: calls.append(a) or _FakeCompleted(0))
    marker = str(tmp_path / ".running")
    rc = k8s.host_launch_k8s(cfg, args, marker)
    assert rc == 16  # infrastructure defect, not a ticket defect
    assert calls == []  # no ConfigMap/Job was created
    assert not os.path.exists(marker)  # no run was started


def test_gate_runs_before_cluster_calls(tmp_path, monkeypatch):
    repo, cfg = _k8s_repo(tmp_path)
    args = _k8s_args(tmp_path)
    order = []
    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(preflight, "_preflight",
                        lambda cfg: order.append("gate") or None)
    # image delivery: the digest resolution is a docker call, not a cluster
    # call — mocked here (the delivery logic itself: test_k8s_image_delivery.py)
    monkeypatch.setattr(k8s, "_image_ref",
                        lambda cfg: ("192.168.122.156:5000/stanok-machine@sha256:fake", None))
    monkeypatch.setattr(k8s, "pack_tree", lambda root: "x")  # base64 str
    monkeypatch.setattr(k8s, "transport_ok", lambda blob: True)
    _no_real_cluster_calls(monkeypatch)

    def stop(*a, **k):
        order.append(a[0])
        return _FakeCompleted(1, stderr="stop-here")  # -> _kubectl_checked raises
    monkeypatch.setattr(kube, "_kubectl", stop)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert order == ["gate", "create"]  # gate first, resources after it
    assert rc == 16  # the failed cluster call -> infra path
    # P0: nothing was created -> the finally must NOT touch the cluster.
    # A foreign resource with a colliding name is never deleted.
    assert "delete" not in order


def test_cleanup_deletes_only_created_resources(tmp_path, monkeypatch):
    # P0 (operator 2026-10-11): the finally deletes exactly the resources
    # this run created (ownership proven by a successful create). The fresh
    # Job / patch ConfigMap are never created here (the run aborts before
    # the fresh check) -> their names must not appear in any delete.
    repo, cfg = _k8s_repo(tmp_path)
    args = _k8s_args(tmp_path)
    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(preflight, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "_image_ref",
                        lambda cfg: ("192.168.122.156:5000/stanok-machine@sha256:fake", None))
    monkeypatch.setattr(k8s, "pack_tree", lambda root: "x")
    monkeypatch.setattr(k8s, "transport_ok", lambda blob: True)
    _no_real_cluster_calls(monkeypatch)
    calls = []

    def fake(*a, **k):
        calls.append(a)
        return _FakeCompleted(0)  # every create succeeds
    monkeypatch.setattr(kube, "_kubectl", fake)
    monkeypatch.setattr(k8s, "_pod_of_job", lambda *a, **k: None)
    monkeypatch.setattr(k8s, "_wait_job_terminal", lambda *a, **k: "failed")
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert rc == 17  # no payload block -> aborted, as designed
    creates = [a for a in calls if a[0] == "create" and a[1] == "configmap"]
    assert {a[2] for a in creates} == {"stanok-ticket-lbl", "stanok-tree-lbl",
                                       "stanok-runner-lbl"}
    assert ("create", "-f", "-") in calls  # the Job lands via create, not apply
    deletes = [a for a in calls if a[0] == "delete"]
    assert {(a[1], a[2]) for a in deletes} == {
        ("configmap", "stanok-ticket-lbl"), ("configmap", "stanok-tree-lbl"),
        ("configmap", "stanok-runner-lbl"), ("job", "stanok-job-lbl")}


# --- 10: image provenance (operator plan 2026-10-12) ----------------------------

def test_pod_image_id_reads_the_pod_record(monkeypatch):
    # the runtime's own record (containerStatuses.imageID), not the host store
    seen = []

    def fake(*a, **k):
        seen.append(a)
        return _FakeCompleted(0, "sha256:913ad405b489\n")
    monkeypatch.setattr(kube, "_kubectl", fake)
    assert k8s._pod_image_id("pod-x", "default") == "sha256:913ad405b489"
    assert seen == [("get", "pod", "pod-x", "-n", "default",
                     "-o", "jsonpath={.status.containerStatuses[0].imageID}")]


def test_pod_image_id_accepts_containerd_registry_qualified_form(monkeypatch):
    # live defect (verify-registry run, 2026-10-12): containerd/k3s reports
    # "<repo>@sha256:<hex>", not the bare docker form — the DEFAULT runtime
    # must be accepted (it is the stronger proof: it names the registry).
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(
        0, "192.168.122.156:5000/stanok-machine@sha256:20a61e6943f4\n"))
    assert k8s._pod_image_id("pod-x", "default") == \
        "192.168.122.156:5000/stanok-machine@sha256:20a61e6943f4"


def test_pod_image_id_fail_soft_is_none(monkeypatch):
    # no pod / kubectl error / non-digest value -> None (explicit, never a guess)
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: _FakeCompleted(0, "sha256:abc"))
    assert k8s._pod_image_id(None, "default") is None
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: _FakeCompleted(1, "", "not found"))
    assert k8s._pod_image_id("pod-x", "default") is None
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: _FakeCompleted(0, "stanok-machine:latest"))
    assert k8s._pod_image_id("pod-x", "default") is None
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(0, ""))
    assert k8s._pod_image_id("pod-x", "default") is None


# --- Verdict cross-check (external review 2026-10-16): internal_rc vs summary rc ---

def _payload_host_run(tmp_path, monkeypatch, payload, real_apply=False):
    """Drive host_launch_k8s to the payload stage with a synthetic payload
    (extract_payload mocked — the nonce framing is tested in the transport
    tests); the post-payload stages are mocked so the test isolates the
    internal-rc comparison. real_apply=True leaves apply_patch_scratch
    REAL (wave C scratch-failure test); the default keeps every earlier
    test's mocked flow byte-identical. Returns (cfg, rc)."""
    repo, cfg = _k8s_repo(tmp_path)
    args = _k8s_args(tmp_path)
    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(preflight, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "_image_ref",
                        lambda cfg: ("192.168.122.156:5000/stanok-machine@sha256:fake", None))
    monkeypatch.setattr(k8s, "pack_tree", lambda root: "x")
    monkeypatch.setattr(k8s, "transport_ok", lambda blob: True)
    _no_real_cluster_calls(monkeypatch)
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(0))
    monkeypatch.setattr(k8s, "_pod_of_job", lambda *a, **k: None)
    monkeypatch.setattr(k8s, "_wait_job_terminal", lambda *a, **k: "succeeded")
    # The payload path requires pod-stdout.log to exist; its content is
    # irrelevant — extract_payload is mocked to return the synthetic payload.
    _, live_dir = cfg.label_paths("lbl")
    os.makedirs(live_dir, exist_ok=True)
    with open(os.path.join(live_dir, "pod-stdout.log"), "w", encoding="utf-8") as f:
        f.write("synthetic")
    monkeypatch.setattr(k8s, "extract_payload", lambda text, nonce: payload)
    # Post-payload stages: mocked so the test is about the comparison only.
    monkeypatch.setattr(patchgate, "patch_gate", lambda text: [])
    if not real_apply:
        monkeypatch.setattr(k8s, "apply_patch_scratch",
                            lambda blob, text: str(tmp_path / "scratch"))
    monkeypatch.setattr(k8s, "scratch_contract_violations",
                        lambda cfg, before, scratch, declared: [])
    monkeypatch.setattr(k8s, "_fresh_job", lambda *a, **k: (0, "green"))
    return cfg, k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))


def _summary_payload(rc):
    return {
        "changes.patch": b"",
        "summary.json": json.dumps({"rc": rc, "verifier": "PASS",
                                    "probe_result": "PROBE-PASS"}).encode("utf-8"),
    }


def test_internal_rc_contradicting_summary_is_infra_defect(tmp_path, monkeypatch):
    # summary.json claims rc=0 (PASS) but the in-Pod session exited 1 —
    # one channel substituted a verdict: infrastructure defect (rc=16), the
    # worker verdict is never published as a verdict.
    payload = _summary_payload(0)
    payload["internal_rc.txt"] = b"1\n"
    cfg, rc = _payload_host_run(tmp_path, monkeypatch, payload)
    assert rc == 16
    evidence_dir, _ = cfg.label_paths("lbl")
    with open(os.path.join(evidence_dir, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["rc"] == 16
    assert summary["probe_result"] == "ENV-FAIL"
    with open(os.path.join(evidence_dir, "failures.log"), encoding="utf-8") as f:
        text = f.read()
    assert "verdict-substitution" in text
    assert "exit 1" in text and "rc=0" in text  # both channels named


def test_internal_rc_matching_summary_is_not_a_defect(tmp_path, monkeypatch):
    # Positive control: internal_rc == summary rc -> the comparison is inert,
    # the normal flow continues (here: published PASS, rc=0).
    payload = _summary_payload(0)
    payload["internal_rc.txt"] = b"0\n"
    cfg, rc = _payload_host_run(tmp_path, monkeypatch, payload)
    assert rc == 0
    evidence_dir, _ = cfg.label_paths("lbl")
    with open(os.path.join(evidence_dir, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["rc"] == 0
    assert summary["probe_result"] != "ENV-FAIL"


def test_internal_rc_absent_is_no_check(tmp_path, monkeypatch):
    # An image predating the contract ships no internal_rc.txt — the host
    # must not invent a mismatch: the flow continues unchanged.
    payload = _summary_payload(0)
    cfg, rc = _payload_host_run(tmp_path, monkeypatch, payload)
    assert rc == 0
    evidence_dir, _ = cfg.label_paths("lbl")
    with open(os.path.join(evidence_dir, "summary.json"), encoding="utf-8") as f:
        assert json.load(f)["rc"] == 0


def test_missing_summary_payload_names_internal_exit(tmp_path, monkeypatch):
    # Payload block WITHOUT a summary.json: still aborted (rc=17, status
    # 'missing') — but the in-Pod exit code, if the payload carried one, is
    # named in the abort log: the session ran and died, the transport did
    # not deliver a verdict.
    payload = {"changes.patch": b"", "internal_rc.txt": b"137\n"}
    logs = []
    monkeypatch.setattr(k8s, "log", lambda *a: logs.append(" ".join(map(str, a))))
    _, rc = _payload_host_run(tmp_path, monkeypatch, payload)
    assert rc == 17
    assert any("exit code was 137" in line for line in logs)


# --- wave C (operator 2026-10-20): scratch setup failure is a verdict, not a crash ---

def test_scratch_setup_failure_publishes_contract_fail(tmp_path, monkeypatch):
    # End-to-end with the REAL apply_patch_scratch: tempfile.mkdtemp fails
    # (OSError) -> the caller's RuntimeError->PATCH-APPLY mapping must
    # produce a published CONTRACT-FAIL verdict (rc=1), not an uncaught
    # exception escaping host_launch_k8s (no except Exception exists there
    # — only KeyboardInterrupt/finally). The "PATCH-APPLY" literal is
    # characterization (source: k8s.py call site); "CONTRACT-FAIL" is the
    # existing _publish_evidence vocabulary.
    def boom(*a, **k):
        raise OSError("mkdtemp: no space left on device")
    monkeypatch.setattr(k8s.tempfile, "mkdtemp", boom)
    payload = _summary_payload(0)
    payload["internal_rc.txt"] = b"0\n"
    cfg, rc = _payload_host_run(tmp_path, monkeypatch, payload, real_apply=True)
    assert rc == 1
    evidence_dir, _ = cfg.label_paths("lbl")
    with open(os.path.join(evidence_dir, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["rc"] == 1
    assert summary["probe_result"] == "CONTRACT-FAIL"
    with open(os.path.join(evidence_dir, "failures.log"), encoding="utf-8") as f:
        assert "PATCH-APPLY" in f.read()
