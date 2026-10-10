"""CC-231 (production cutover, supersedes the P1 §3 default) — the runtime switch.

launch.sh keeps its contract (`run <ticket> <label> --follow`, status/wait/
stop unchanged); k8s is the DEFAULT runtime: absent/any other value = the
host orchestrator (k8s.host_launch_k8s); the Docker path (deprecated
fallback, launcher/sandbox.py) runs ONLY on an explicit STANOK_RUNTIME=docker,
with a loud WARNING on stderr. The switch is a pure function so the dispatch
is testable without a cluster. Tests:
  1  default (env unset) -> "k8s"
  2  STANOK_RUNTIME=docker -> "docker" (the only Docker opt-in)
  3  STANOK_RUNTIME=k8s -> "k8s" (explicit, same as default)
  4  the k8s host driver exists with the entry the dispatcher calls
  5  the explicit-Docker opt-in prints the deprecation WARNING
 CC-232 (pre-flight doctor gate):
  6  _cluster_env: KUBECONFIG fallback to ~/.kube/config (operator host)
  7  _preflight_cluster: node-Ready and manifest-test branches
  8  host_launch_k8s: gate aborts (rc=16) BEFORE any cluster call; when the
     gate passes, the cluster calls follow it (order proven)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_wiring.py -q
"""
import argparse
import os
import sys

from launcher import cli, k8s
from launcher.config import Config


def test_default_runtime_is_k8s(monkeypatch):
    monkeypatch.delenv("STANOK_RUNTIME", raising=False)
    assert cli._runtime_mode() == "k8s"


def test_docker_only_on_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("STANOK_RUNTIME", "docker")
    assert cli._runtime_mode() == "docker"
    # any other value is NOT a Docker opt-in (the old default semantics are
    # gone: a typo no longer silently selects the deprecated path)
    monkeypatch.setenv("STANOK_RUNTIME", "k8s")
    assert cli._runtime_mode() == "k8s"
    monkeypatch.setenv("STANOK_RUNTIME", "")
    assert cli._runtime_mode() == "k8s"


def test_host_driver_entry_exists():
    assert callable(k8s.host_launch_k8s)


def test_deprecated_docker_warning(capsys):
    cli._warn_deprecated_docker()
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "deprecated insecure Docker runtime" in err
    assert "seccomp/apparmor unconfined" in err


# --- 6: CC-232 _cluster_env (kubectl config fallback, operator host) ---------------

def test_cluster_env_falls_back_to_user_kubeconfig(tmp_path, monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    kc = tmp_path / ".kube" / "config"
    kc.parent.mkdir()
    kc.write_text("x", encoding="utf-8")
    assert k8s._cluster_env()["KUBECONFIG"] == str(kc)
    # an explicit KUBECONFIG is never overridden
    monkeypatch.setenv("KUBECONFIG", "/somewhere/else")
    assert k8s._cluster_env()["KUBECONFIG"] == "/somewhere/else"


def test_cluster_env_no_fallback_without_kubeconfig(tmp_path, monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no .kube/config there
    assert "KUBECONFIG" not in k8s._cluster_env()


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
    assert k8s._preflight_cluster(cfg) is None
    assert seen == ["nodes", "pytest"]  # both checks ran


def test_preflight_cluster_unreachable_is_reason(monkeypatch):
    _fake_cluster(monkeypatch, nodes_rc=1)
    cfg = Config(repo_root="/tmp", log_dir="/tmp")
    reason = k8s._preflight_cluster(cfg)
    assert reason and "cluster unreachable" in reason


def test_preflight_cluster_not_ready_node_is_reason(monkeypatch):
    _fake_cluster(monkeypatch, nodes_out="hermes   NotReady   control-plane\n")
    cfg = Config(repo_root="/tmp", log_dir="/tmp")
    reason = k8s._preflight_cluster(cfg)
    assert reason and "not Ready" in reason


def test_preflight_cluster_manifest_drift_is_reason(monkeypatch):
    _fake_cluster(monkeypatch, pytest_rc=1)
    cfg = Config(repo_root="/tmp", log_dir="/tmp")
    reason = k8s._preflight_cluster(cfg)
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


def test_gate_aborts_before_any_cluster_call(tmp_path, monkeypatch):
    repo, cfg = _k8s_repo(tmp_path)
    args = _k8s_args(tmp_path)
    calls = []
    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(k8s, "_preflight_cluster",
                        lambda cfg: "cluster unreachable: mock")
    monkeypatch.setattr(k8s, "_kubectl_checked", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(k8s, "_apply_manifest", lambda text: calls.append("apply"))
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
    monkeypatch.setattr(k8s, "_preflight_cluster",
                        lambda cfg: order.append("gate") or None)
    monkeypatch.setattr(k8s, "pack_tree", lambda root: "x")  # base64 str
    monkeypatch.setattr(k8s, "transport_ok", lambda blob: True)

    def stop(*a, **k):
        order.append("cluster")
        raise RuntimeError("stop-here")
    monkeypatch.setattr(k8s, "_kubectl_checked", stop)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert order == ["gate", "cluster"]  # gate first, resources after it
    assert rc == 16  # the mocked cluster call raised -> infra path
