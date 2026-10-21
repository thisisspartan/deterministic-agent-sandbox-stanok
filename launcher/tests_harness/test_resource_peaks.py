"""Resource measurement — kubelet sampling during a run (host-side, 2026-10-16).

The gap (operator decision 2026-10-16): the Job templates carry requests/
limits approved in bb5eed6 as "pending measured peaks" — nothing ever
measured them. The mechanism is the native kubelet primitive (`kubectl get
--raw /api/v1/nodes/<node>/proxy/stats/summary`, 10s housekeeping) sampled
read-only while a Job runs; observed peaks are host-stamped into
summary.json as resource_peaks, like patch_sha256. The sampler never
changes the run it observes: fetch errors are counted, never raised; no
sample -> None, never a 0 masquerade.

Tests (synthetic kubelet fixtures; no test reaches a real cluster):
  1  _peak_from_stats: typed extraction from a kubelet summary; wrong ns,
     absent pod -> None; absent cpu/memory sections -> None fields
  2  _ResourceSampler: max-tracking over monotonic samples (peak == the
     last value, samples counted); all-errors -> None; pod never in stats
     -> samples 0 -> None; None fields never clobber a known peak, a later
     value fills them; max ignores None;
     2b py311 join contract: the same functional path on python3.11 (the
     image's version) — CPython 3.11 join() calls self._stop(), an Event
     named _stop shadows it (TypeError); skipped when python3.11 absent
  3  _node_of_pod / _kubelet_stats: kubectl wrappers, fail-soft to None
  4  _fresh_job wiring: with a peaks holder the sampler runs and the holder
     is filled on BOTH the success and the failure path; without a holder
     the pre-measurement flow is unchanged (no pod resolution, no sampler)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_resource_peaks.py -q
"""
import json
import os
import pathlib
import shutil
import subprocess
import time

import pytest

from launcher import k8s, kube, peaks
from launcher.config import Config

FAKE_IMAGE = "192.168.122.156:5000/stanok-machine@sha256:fake"
POD = "stanok-job-lbl-xyz"
NS = "default"


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _stats(cpu, mem_usage, mem_ws, name=POD, ns=NS):
    return {"pods": [{"podRef": {"name": name, "namespace": ns},
                      "cpu": {"usageNanoCores": cpu},
                      "memory": {"usageBytes": mem_usage,
                                 "workingSetBytes": mem_ws}}]}


# --- 1: _peak_from_stats — pure extraction ---------------------------------------

def test_extraction_typed_record():
    stats = {"pods": [
        {"podRef": {"name": "other", "namespace": NS}},
        {"podRef": {"name": POD, "namespace": NS},
         "cpu": {"usageNanoCores": 123456},
         "memory": {"usageBytes": 111, "workingSetBytes": 222}}]}
    assert peaks._peak_from_stats(stats, POD, NS) == {
        "cpu_peak_nanocores": 123456, "mem_peak_usage_bytes": 111,
        "mem_peak_working_set_bytes": 222}


def test_extraction_wrong_namespace_or_absent_is_none():
    stats = _stats(1, 2, 3, ns="other-ns")
    assert peaks._peak_from_stats(stats, POD, NS) is None
    assert peaks._peak_from_stats({"pods": []}, POD, NS) is None
    assert peaks._peak_from_stats({}, POD, NS) is None


def test_extraction_missing_sections_are_none_fields_not_zero():
    peak = peaks._peak_from_stats({"pods": [{"podRef": {"name": POD,
                                                       "namespace": NS}}]},
                                POD, NS)
    assert peak == {"cpu_peak_nanocores": None, "mem_peak_usage_bytes": None,
                    "mem_peak_working_set_bytes": None}


# --- 2: _ResourceSampler — max-tracking, never fatal, never a 0 masquerade -------

def test_sampler_tracks_max_over_monotonic_samples():
    n = {"i": 0}

    def fetch():
        n["i"] += 1
        return _stats(100 * n["i"], 1000 * n["i"], 900 * n["i"])

    s = peaks._ResourceSampler(POD, NS, interval_s=0.02, fetch=fetch)
    s.start()
    time.sleep(0.12)
    out = s.stop_and_peaks()
    assert out is not None and out["samples"] >= 2
    assert out["errors"] == 0
    # monotonic fetch: the peak IS the last observed value, exactly
    assert out["cpu_peak_nanocores"] == 100 * out["samples"]
    assert out["mem_peak_usage_bytes"] == 1000 * out["samples"]
    assert out["mem_peak_working_set_bytes"] == 900 * out["samples"]


def test_sampler_all_errors_publishes_none():
    def fetch():
        raise RuntimeError("kubelet unreachable")

    s = peaks._ResourceSampler(POD, NS, interval_s=0.02, fetch=fetch)
    s.start()
    time.sleep(0.06)
    out = s.stop_and_peaks()
    assert out is None  # never a 0 masquerade
    assert s.errors >= 1 and s.samples == 0


def test_sampler_pod_never_in_stats_publishes_none():
    s = peaks._ResourceSampler(POD, NS, interval_s=0.02,
                             fetch=lambda: _stats(1, 2, 3, name="other-pod"))
    s.start()
    time.sleep(0.06)
    assert s.stop_and_peaks() is None
    assert s.samples == 0  # a sample without the pod is not a sample


def test_sampler_merge_max_ignores_none_and_fills_later():
    seq = [
        _stats(None, None, None),          # all-None first: peak exists, empty
        _stats(50, 5000, 4000),            # fills the fields
        _stats(30, 9000, 3000),            # cpu lower (max keeps 50), mem higher
    ]
    i = {"n": 0}

    def fetch():
        stats = seq[min(i["n"], len(seq) - 1)]
        i["n"] += 1
        return stats

    s = peaks._ResourceSampler(POD, NS, interval_s=0.02, fetch=fetch)
    s.start()
    time.sleep(0.10)
    out = s.stop_and_peaks()
    assert out["cpu_peak_nanocores"] == 50
    assert out["mem_peak_usage_bytes"] == 9000
    assert out["mem_peak_working_set_bytes"] == 4000


_PY311_SCRIPT = """
import sys, time
sys.path.insert(0, sys.argv[1])
from launcher import peaks
s = peaks._ResourceSampler("p", "default", interval_s=0.02, fetch=lambda: {
    "pods": [{"podRef": {"name": "p", "namespace": "default"},
              "cpu": {"usageNanoCores": 7},
              "memory": {"usageBytes": 8, "workingSetBytes": 9}}]})
s.start()
time.sleep(0.08)
out = s.stop_and_peaks()
assert out is not None and out["samples"] >= 1
assert out["cpu_peak_nanocores"] == 7
print("py311-join-ok")
"""


def test_py311_join_contract():
    """External review 2026-10-16 (P1), reproduced on 3.11.15: CPython 3.11
    Thread._wait_for_tstate_lock calls self._stop() inside join() — an Event
    attribute named _stop shadows the internal and stop_and_peaks() raises
    TypeError. The host venv is 3.13, so the functional tests above cannot
    see this class; the production image is 3.11 (bookworm), so a launcher
    running on the image's version would hit it. Runs the same functional
    path on python3.11 when available (STANOK_PY311 or PATH)."""
    py = os.environ.get("STANOK_PY311") or shutil.which("python3.11")
    if not py:
        pytest.skip("python3.11 not available — image version untestable here")
    repo = str(pathlib.Path(__file__).resolve().parents[2])
    r = subprocess.run([py, "-c", _PY311_SCRIPT, repo],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"python3.11 join contract failed:\n{r.stderr}"
    assert "py311-join-ok" in r.stdout


# --- 3: kubectl wrappers -----------------------------------------------------------

def test_node_of_pod_fail_soft(monkeypatch):
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: _FakeCompleted(0, " node-a\n"))
    assert peaks._node_of_pod(POD, NS) == "node-a"
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(1, ""))
    assert peaks._node_of_pod(POD, NS) is None
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(0, ""))
    assert peaks._node_of_pod(POD, NS) is None


def test_kubelet_stats_parses_json(monkeypatch):
    monkeypatch.setattr(kube, "_kubectl_checked",
                        lambda *a, **k: _FakeCompleted(0, '{"pods": []}'))
    assert peaks._kubelet_stats("node-a") == {"pods": []}


# --- 4: _fresh_job wiring — holder filled, no-holder flow unchanged ---------------

class _FakeSampler:
    def __init__(self, pod, ns, **kw):
        self.pod, self.ns = pod, ns
        self.stopped = False

    def start(self):
        pass

    def stop_and_peaks(self):
        self.stopped = True
        return {"cpu_peak_nanocores": 7, "mem_peak_usage_bytes": 8,
                "mem_peak_working_set_bytes": 9, "samples": 1, "errors": 0}


def _fresh_env(tmp_path, monkeypatch, *, wait_result, pod_json):
    cfg = Config(repo_root=str(tmp_path), log_dir=str(tmp_path / "logs"))
    patch_file = tmp_path / "changes.patch"
    patch_file.write_text("diff --git a/src/x.py b/src/x.py\n", encoding="utf-8")
    monkeypatch.setattr(kube, "_kubectl_checked", lambda *a, **k: _FakeCompleted(0))
    monkeypatch.setattr(kube, "_create_manifest", lambda text: None)
    monkeypatch.setattr(k8s, "_wait_job_terminal", lambda *a, **k: wait_result)
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(
        0, json.dumps(pod_json)))
    return cfg, patch_file


OOM_POD = {"status": {"phase": "Failed", "containerStatuses": [
    {"name": "fresh", "state": {"terminated": {"exitCode": 128,
                                               "reason": "OOMKilled"}}}]}}


def test_fresh_job_fills_holder_on_success(tmp_path, monkeypatch):
    cfg, patch_file = _fresh_env(tmp_path, monkeypatch, wait_result="complete",
                                 pod_json={})
    monkeypatch.setattr(k8s, "_pod_of_job", lambda *a, **k: "pod-x")
    made = []
    monkeypatch.setattr(peaks, "_ResourceSampler",
                        lambda *a, **k: made.append(1) or _FakeSampler(*a, **k))
    holder = {}
    rc, tail = k8s._fresh_job(cfg, NS, "stanok-fresh-lbl", "cm-tree",
                              "cm-patch", str(patch_file), 60, [], FAKE_IMAGE,
                              holder)
    assert (rc, tail) == (0, "")
    assert made == [1]  # the sampler was constructed
    assert holder["peaks"]["cpu_peak_nanocores"] == 7


def test_fresh_job_fills_holder_on_failure_path(tmp_path, monkeypatch):
    # peaks are captured even when the fresh Pod is OOM-killed — the run that
    # hits the limit is exactly the one whose numbers matter.
    cfg, patch_file = _fresh_env(tmp_path, monkeypatch, wait_result="failed",
                                 pod_json=OOM_POD)
    monkeypatch.setattr(k8s, "_pod_of_job", lambda *a, **k: "pod-x")
    monkeypatch.setattr(peaks, "_ResourceSampler", _FakeSampler)
    holder = {}
    rc, tail = k8s._fresh_job(cfg, NS, "stanok-fresh-lbl", "cm-tree",
                              "cm-patch", str(patch_file), 60, [], FAKE_IMAGE,
                              holder)
    assert rc == 1 and tail.startswith("EXEC_ERROR:") and "OOMKilled" in tail
    assert holder["peaks"]["cpu_peak_nanocores"] == 7


def test_fresh_job_without_holder_is_unchanged(tmp_path, monkeypatch):
    # no holder -> no pod resolution before the wait, no sampler: the
    # pre-measurement flow byte-for-byte.
    cfg, patch_file = _fresh_env(tmp_path, monkeypatch, wait_result="complete",
                                 pod_json={})
    calls = []
    monkeypatch.setattr(k8s, "_pod_of_job",
                        lambda *a, **k: calls.append("pod") or "pod-x")
    monkeypatch.setattr(peaks, "_ResourceSampler",
                        lambda *a, **k: calls.append("sampler") or _FakeSampler(*a, **k))
    rc, tail = k8s._fresh_job(cfg, NS, "stanok-fresh-lbl", "cm-tree",
                              "cm-patch", str(patch_file), 60, [], FAKE_IMAGE)
    assert (rc, tail) == (0, "")
    assert calls == []
