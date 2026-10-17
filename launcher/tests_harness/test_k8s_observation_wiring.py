"""A3 wiring (external review 2026-10-17): the worker-path call sites.

test_timer_contract pins the SUM (deadline + graces < cap) and
test_observation_windows_are_remaining_time... pins the helper
k8s._observation_timeout itself. What neither pins is the WIRING: that the
worker path in host_launch_k8s (k8s.py, the block after `obs_start =
time.monotonic()`) actually calls _observation_timeout at BOTH call sites
with the right graces — _stream_pod_logs with _STREAM_GRACE_S,
_wait_job_terminal with _STREAM_GRACE_S + _TERMINAL_GRACE_S — so each call
receives only the time REMAINING to one absolute end anchored at Job
creation, never a fresh duration. The original defect (review 2026-10-17,
finding 1) was exactly this: fresh per-call durations
(deadline+180)+(deadline+60)=4440 > cap. A helper change that keeps the
sum test green but rewires a call site back to a fresh duration must fail
HERE.

Method: drive host_launch_k8s down the real worker path with the cluster
cycle mocked (same shape as test_k8s_wiring's gate tests) and a stubbed
clock: time.monotonic is a controlled counter, _stream_pod_logs /
_wait_job_terminal record the timeout_s they are handed. The run then
aborts at the payload stage (rc=17, no evidence block) — expected: the
assertions are about the two observation calls, which happen before it.

Cases:
  1  stream gets the full window at call time (deadline + stream grace);
     after the stream consumed 120 s of it, the terminal call gets exactly
     the time remaining to the shared absolute end (120 s) — not a fresh
     duration (2160), not the stream grace (0); order stream -> terminal;
     the stream call carries the live_dir pod-stdout.log path and the Pod.
  2  past the absolute end both windows floor to 0 (max(0, ...) at the
     call sites — a call never receives a negative timeout).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_observation_wiring.py -q
"""
import argparse
import os

from launcher import k8s
from launcher.config import Config

CLOCK_START = 1000.0  # arbitrary monotonic origin for the stubbed clock
STREAM_CONSUMED = 120  # seconds the fake stream "spends" of its window


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(tmp_path / "logs"))


def _args(tmp_path):
    ticket = tmp_path / "ticket.md"
    ticket.write_text("test: tests/x_test.py\nrun.sh: exists\n", encoding="utf-8")
    return argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket), local_retries=0, extra=[])


def _drive(tmp_path, monkeypatch, *, advance_at_pod=None, advance_at_stream=None):
    """host_launch_k8s down the worker observation path with the cluster
    cycle mocked and a controlled clock. Returns (cfg, rc, calls) where
    calls records ("stream"/"terminal", arg3, timeout_s) in call order."""
    repo, cfg = _repo(tmp_path)
    args = _args(tmp_path)
    monkeypatch.delenv("STANOK_K8S_JOB_DEADLINE_S", raising=False)
    monkeypatch.delenv("STANOK_START_COMMIT", raising=False)
    clock = [CLOCK_START]
    monkeypatch.setattr(k8s.time, "monotonic", lambda: clock[0])

    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    monkeypatch.setattr(k8s, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "_image_ref",
                        lambda cfg: ("192.168.122.156:5000/stanok-machine@sha256:fake", None))
    monkeypatch.setattr(k8s, "pack_tree", lambda root: "x")
    monkeypatch.setattr(k8s, "transport_ok", lambda blob: True)
    monkeypatch.setattr(k8s, "_install_signal_handlers", lambda rs: None)

    def guard(*a, **k):
        raise AssertionError(f"real cluster call from test: {a[:3]}")
    monkeypatch.setattr(k8s.subprocess, "run", guard)
    monkeypatch.setattr(k8s, "_kubectl",
                        lambda *a, **k: _FakeCompleted(0))

    def fake_pod(job_name, ns, timeout_s=120):
        if advance_at_pod is not None:
            clock[0] = advance_at_pod
        return "pod-x"
    monkeypatch.setattr(k8s, "_pod_of_job", fake_pod)

    class _DummySampler:
        def __init__(self, pod, ns):
            pass

        def start(self):
            pass

        def stop_and_peaks(self):
            return None
    monkeypatch.setattr(k8s, "_ResourceSampler", _DummySampler)

    calls = []

    def fake_stream(pod, ns, path, timeout_s):
        calls.append(("stream", path, timeout_s))
        if advance_at_stream is not None:
            clock[0] = advance_at_stream
        return True
    monkeypatch.setattr(k8s, "_stream_pod_logs", fake_stream)

    def fake_wait(name, ns, timeout_s):
        calls.append(("terminal", name, timeout_s))
        return "complete"
    monkeypatch.setattr(k8s, "_wait_job_terminal", fake_wait)

    rc = k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    return cfg, rc, calls


# --- 1: both windows are remaining time to ONE absolute end ----------------------

def test_worker_path_hands_remaining_time_not_fresh_durations(tmp_path, monkeypatch):
    deadline = k8s.job_deadline(Config(repo_root=str(tmp_path),
                                       log_dir=str(tmp_path / "logs")))
    cfg, rc, calls = _drive(
        tmp_path, monkeypatch,
        advance_at_stream=CLOCK_START + deadline + STREAM_CONSUMED)
    assert rc == 17  # no payload block -> aborted, as designed (expected here)
    assert [c[0] for c in calls] == ["stream", "terminal"]  # sequential chain

    _, stream_path, stream_t = calls[0]
    _, job_name, terminal_t = calls[1]

    # At the stream call nothing has elapsed since obs_start: the window is
    # the full stream stage of the chain — deadline + stream grace.
    assert stream_t == deadline + k8s._STREAM_GRACE_S
    # The stream consumed 120 s of its window. The terminal call must get
    # only the time remaining to the SHARED absolute end
    # (obs_start + deadline + stream + terminal): 240 - 120 = 120.
    # A fresh duration would be deadline + 60 = 2160; the stream grace
    # alone would give 0 — both wrong values are distinguishable from 120.
    assert terminal_t == k8s._STREAM_GRACE_S + k8s._TERMINAL_GRACE_S - STREAM_CONSUMED
    # The defect class this wiring closes: a fresh per-call duration.
    assert terminal_t < deadline + k8s._TERMINAL_GRACE_S

    # The call sites carry the real arguments: live_dir pod-stdout.log,
    # the Job name the run created.
    _, live_dir = cfg.label_paths("lbl")
    assert stream_path == os.path.join(live_dir, "pod-stdout.log")
    assert job_name == "stanok-job-lbl"


# --- 2: past the absolute end both windows floor to 0 -----------------------------

def test_windows_floor_at_zero_past_the_absolute_end(tmp_path, monkeypatch):
    deadline = k8s.job_deadline(Config(repo_root=str(tmp_path),
                                       log_dir=str(tmp_path / "logs")))
    # The Pod lookup itself ran past the whole chain end: both calls must
    # receive 0 (max(0, ...) at the call sites), never a negative timeout.
    past_end = CLOCK_START + deadline + k8s._STREAM_GRACE_S \
        + k8s._TERMINAL_GRACE_S + 5
    _, rc, calls = _drive(tmp_path, monkeypatch, advance_at_pod=past_end)
    assert rc == 17
    assert [c[0] for c in calls] == ["stream", "terminal"]
    assert calls[0][2] == 0
    assert calls[1][2] == 0
