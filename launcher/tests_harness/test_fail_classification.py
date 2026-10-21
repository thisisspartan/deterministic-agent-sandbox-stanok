"""Stage 2 (review 2026-10-17) — truthful failure classification (B2, B3, B4, A2).

B2  cli.main(), in-process branch: a missing STANOK_LOCK_KEY (git could not
    answer) is an infrastructure failure -> ENV-FAIL rc=16, the same class as
    the docker-runtime refusal (test_k8s_wiring.py) — not a ticket DEFECT (1).
B3  cli._run_session: an infrastructure exception from the session
    (OSError/SubprocessError — model server unreachable, filesystem, a child
    process) -> rc=16, published probe_result ENV-FAIL; a code/contract
    exception (ValueError) stays a DEFECT (rc=1). Not every host exception
    is one class.
B4  cli.cmd_stop: "Stop signal sent"/rc=0 only when SIGTERM was actually
    delivered. Marker without a PID -> rc=1; an already-gone PID -> honest
    "already gone" log, rc=0; a permission denial -> rc=1.
A2  lifecycle._stream_pod_logs: the kubectl exit code is checked — non-zero rc /
    timeout -> False with a distinct log line; host_launch_k8s names the
    stream failure in the missing-payload abort, so a failed stream is
    distinguishable from "the Pod produced no logs".

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_fail_classification.py -q
"""
import argparse
import json
import os
import signal
import subprocess
import time

from launcher import cli, k8s, kube, lifecycle, peaks, payload, preflight
from launcher.config import Config, RunState


def _repo_cfg(tmp_path):
    """A synthetic repo + log dir, the same shape as test_k8s_wiring._k8s_repo."""
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(tmp_path / "logs"))


def _run_args(tmp_path):
    ticket = tmp_path / "ticket.md"
    ticket.write_text("test: tests/x_test.py\nrun.sh: exists\n", encoding="utf-8")
    return argparse.Namespace(cmd="run", label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket), local_retries=0, extra=[],
                             follow=False)


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _capture(monkeypatch, module):
    lines = []
    monkeypatch.setattr(module, "log", lambda *a: lines.append(" ".join(map(str, a))))
    return lines


# --- B2: missing lock key is an infrastructure refusal (rc=16) --------------------

def test_missing_lock_key_is_env_fail(tmp_path, monkeypatch):
    # The in-process branch (STANOK_NO_SANDBOX) with no lock key: git could
    # not answer — infrastructure, not a ticket defect. The docker branch
    # (test_k8s_wiring.test_docker_runtime_env_is_refused) is the precedent
    # for the classification; this test pins the lock branch to the same rc.
    repo, cfg = _repo_cfg(tmp_path)
    args = _run_args(tmp_path)
    monkeypatch.setenv("STANOK_NO_SANDBOX", "1")
    monkeypatch.delenv("STANOK_IN_CONTAINER", raising=False)
    monkeypatch.delenv("STANOK_LOCK_KEY", raising=False)
    monkeypatch.delenv("STANOK_RUNTIME", raising=False)
    monkeypatch.setattr(cli.Config, "from_env", classmethod(lambda cls: cfg))

    class _StubParser:
        def parse_args(self):
            return args
    monkeypatch.setattr(cli, "_build_parser", lambda cfg: _StubParser())
    monkeypatch.setattr(cli, "_capture_start_commit", lambda cfg: None)
    monkeypatch.setattr(cli, "_lock_key", lambda cfg: None)  # git cannot answer
    monkeypatch.setattr(cli, "_launch_gates", lambda cfg, args: None)

    def no_run(*a, **k):
        raise AssertionError("a refused launch must not reach cmd_run")
    monkeypatch.setattr(cli, "cmd_run", no_run)

    rc = cli.main()
    assert rc == 16  # ENV-FAIL, not DEFECT (1)
    d = cfg.summary_dir("lbl")
    with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["rc"] == 16
    with open(os.path.join(d, "failures.log"), encoding="utf-8") as f:
        assert "lock key unavailable" in f.read()


# --- B3: the session's last-resort net distinguishes infrastructure from bugs ----

def _run_state(cfg):
    evidence_dir, live_dir = cfg.label_paths("lbl")
    os.makedirs(evidence_dir, exist_ok=True)
    os.makedirs(live_dir, exist_ok=True)
    return RunState(evidence_dir=evidence_dir, live_dir=live_dir,
                    marker_path=os.path.join(evidence_dir, ".running"))


def _run_session_with(monkeypatch, cfg, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(cli, "run_continuous_session", boom)
    monkeypatch.setattr(cli, "opik_traces_field", lambda: None)
    job = {"label": "lbl", "ticket": "ticket.md"}
    rc = cli._run_session(cfg, _run_state(cfg), job, "prompt", 0, None, 0)
    d = cfg.summary_dir("lbl")
    with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    failures = ""
    p = os.path.join(d, "failures.log")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            failures = f.read()
    return rc, summary, failures


def test_session_infra_exception_is_env_fail(tmp_path, monkeypatch):
    # A model-server connection failure is infrastructure: rc=16, the summary
    # publishes ENV-FAIL (_status_fields), the exception text reaches
    # failures.log — the ticket retries are not burned on it.
    repo, cfg = _repo_cfg(tmp_path)
    rc, summary, failures = _run_session_with(
        monkeypatch, cfg, ConnectionError("model server unreachable"))
    assert rc == 16
    assert summary["rc"] == 16
    assert summary["probe_result"] == "ENV-FAIL"
    assert "model server unreachable" in failures


def test_session_code_exception_stays_defect(tmp_path, monkeypatch):
    # Positive control: a genuine code/contract bug is NOT reclassified —
    # it stays a DEFECT (rc=1), never ENV-FAIL.
    repo, cfg = _repo_cfg(tmp_path)
    rc, summary, failures = _run_session_with(
        monkeypatch, cfg, ValueError("bug in the host layer"))
    assert rc == 1
    assert summary["rc"] == 1
    assert summary["probe_result"] != "ENV-FAIL"
    assert "bug in the host layer" in failures


# --- B4: cmd_stop reports only what it actually did ------------------------------

def _marker(cfg, content):
    evidence_dir, _ = cfg.label_paths("lbl")
    os.makedirs(evidence_dir, exist_ok=True)
    marker = os.path.join(evidence_dir, ".running")
    with open(marker, "w", encoding="utf-8") as f:
        f.write(content)
    return marker


def test_stop_marker_without_pid_fails(tmp_path, monkeypatch):
    # A marker carrying only a start_ts: there is nothing to signal — stop
    # must not claim a signal was sent.
    repo, cfg = _repo_cfg(tmp_path)
    logs = _capture(monkeypatch, cli)
    _marker(cfg, f"{int(time.time())}\n")
    rc = cli.cmd_stop(cfg, "lbl")
    assert rc == 1
    assert any("no PID" in line for line in logs)
    assert not any("Stop signal sent" in line for line in logs)


def test_stop_alive_process_receives_sigterm(tmp_path, monkeypatch):
    # The honest success path: a real child in its own process group gets
    # SIGTERM (wait() proves it) and only then "Stop signal sent".
    repo, cfg = _repo_cfg(tmp_path)
    logs = _capture(monkeypatch, cli)
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    _marker(cfg, f"{int(time.time())} {proc.pid}\n")
    rc = cli.cmd_stop(cfg, "lbl")
    assert rc == 0
    assert proc.wait() == -signal.SIGTERM
    assert any("Stop signal sent" in line for line in logs)


def test_stop_dead_process_is_reported_gone(tmp_path, monkeypatch):
    # The process is already reaped: no signal was delivered — the log says
    # "already gone", never "Stop signal sent" (rc 0: nothing runs).
    repo, cfg = _repo_cfg(tmp_path)
    logs = _capture(monkeypatch, cli)
    proc = subprocess.Popen(["true"])
    proc.wait()
    _marker(cfg, f"{int(time.time())} {proc.pid}\n")
    rc = cli.cmd_stop(cfg, "lbl")
    assert rc == 0
    assert any("already gone" in line for line in logs)
    assert not any("Stop signal sent" in line for line in logs)


def test_stop_permission_denied_is_failure(tmp_path, monkeypatch):
    # A process that exists but may not be signalled: a failure (rc 1),
    # not a claimed success. The denial is simulated (os.killpg/os.kill
    # raise PermissionError) — a real un-signalable pid (e.g. pid 1) would
    # signal the operator's own process group and kill the session.
    repo, cfg = _repo_cfg(tmp_path)
    logs = _capture(monkeypatch, cli)
    _marker(cfg, f"{int(time.time())} 4242\n")

    def deny(pid, sig):
        raise PermissionError
    monkeypatch.setattr(os, "killpg", deny)
    monkeypatch.setattr(os, "kill", deny)
    rc = cli.cmd_stop(cfg, "lbl")
    assert rc == 1
    assert any("no permission" in line for line in logs)
    assert not any("Stop signal sent" in line for line in logs)


# --- A2: the log stream's exit code is checked and named -------------------------

def _stream_env(monkeypatch):
    # lifecycle binds `log` from launcher.logs directly — the stub for a
    # moved function's log call sits on lifecycle (single-home rule); the
    # `k8s.subprocess` patches in the stream tests stay: subprocess is the
    # shared module object in every importer (portion-2 precedent).
    logs = _capture(monkeypatch, lifecycle)
    monkeypatch.setattr(kube, "_cluster_env", lambda: {})
    monkeypatch.setattr(kube, "_kubectl_bin", lambda: "kubectl")
    return logs


def test_stream_pod_logs_nonzero_rc_is_a_stream_failure(tmp_path, monkeypatch):
    # The discarded returncode was the finding: kubectl exiting non-zero is
    # a stream failure (False) with a line naming the rc — never silence.
    logs = _stream_env(monkeypatch)
    monkeypatch.setattr(k8s.subprocess, "run",
                        lambda argv, **kw: _FakeCompleted(1, "", "pods not found"))
    ok = lifecycle._stream_pod_logs("pod-x", "default", str(tmp_path / "out.log"), 5)
    assert ok is False
    assert any("rc=1" in line and "log stream failed" in line for line in logs)


def test_stream_pod_logs_timeout_is_a_stream_failure(tmp_path, monkeypatch):
    logs = _stream_env(monkeypatch)

    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="kubectl", timeout=5)
    monkeypatch.setattr(k8s.subprocess, "run", boom)
    ok = lifecycle._stream_pod_logs("pod-x", "default", str(tmp_path / "out.log"), 5)
    assert ok is False
    assert any("host timeout" in line for line in logs)


def test_stream_pod_logs_zero_rc_is_success(tmp_path, monkeypatch):
    # Positive control: the normal stream returns True, no failure line.
    logs = _stream_env(monkeypatch)
    monkeypatch.setattr(k8s.subprocess, "run",
                        lambda argv, **kw: _FakeCompleted(0, "worker stdout"))
    ok = lifecycle._stream_pod_logs("pod-x", "default", str(tmp_path / "out.log"), 5)
    assert ok is True
    assert not any("log stream failed" in line for line in logs)


class _SamplerStub:
    def __init__(self, pod, ns):
        pass

    def start(self):
        pass

    def stop_and_peaks(self):
        return None


def _missing_payload_run(tmp_path, monkeypatch, stream_ok):
    """Drive host_launch_k8s to the missing-payload abort with the stream
    result fixed by the test; returns (rc, logs)."""
    repo, cfg = _repo_cfg(tmp_path)
    args = _run_args(tmp_path)
    logs = _capture(monkeypatch, k8s)
    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(preflight, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "_image_ref",
                        lambda cfg: ("192.168.122.156:5000/stanok-machine@sha256:fake", None))
    monkeypatch.setattr(payload, "pack_tree", lambda root: "x")
    monkeypatch.setattr(payload, "transport_ok", lambda blob: True)
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(0))
    monkeypatch.setattr(lifecycle, "_pod_of_job", lambda *a, **k: "pod-x")
    monkeypatch.setattr(peaks, "_ResourceSampler", _SamplerStub)
    monkeypatch.setattr(lifecycle, "_stream_pod_logs",
                        lambda *a, **k: stream_ok)  # writes nothing
    monkeypatch.setattr(lifecycle, "_wait_job_terminal", lambda *a, **k: "failed")
    monkeypatch.setattr(lifecycle, "_pod_infra_cause", lambda *a, **k: None)
    monkeypatch.setattr(lifecycle, "_job_infra_cause", lambda *a, **k: None)
    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    return rc, logs


def test_missing_payload_names_the_stream_failure(tmp_path, monkeypatch):
    # The finding's observable consequence: a failed stream and "no logs"
    # produced the same abort text. Now the stream failure is named.
    rc, logs = _missing_payload_run(tmp_path, monkeypatch, stream_ok=False)
    assert rc == 17
    assert any("no evidence payload block" in line for line in logs)
    assert any("kubectl logs -f failed" in line for line in logs)


def test_missing_payload_without_stream_failure_is_unchanged(tmp_path, monkeypatch):
    # Positive control: a successful stream that produced no payload block —
    # the abort text must NOT claim a stream failure.
    rc, logs = _missing_payload_run(tmp_path, monkeypatch, stream_ok=True)
    assert rc == 17
    assert any("no evidence payload block" in line for line in logs)
    assert not any("kubectl logs -f failed" in line for line in logs)
