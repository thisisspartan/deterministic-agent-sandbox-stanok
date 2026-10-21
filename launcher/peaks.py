"""peaks — the resource-measurement cluster (wave A portion 5, 2026-10-21;
names and bodies moved VERBATIM from launcher/k8s.py).

Read-only kubelet sampling (operator decision 2026-10-16): the G1
requests/limits (bb5eed6) were committed as "pending measured peaks" — this
closes the measurement half. The sampler polls the kubelet stats API
(`kubectl get --raw /api/v1/nodes/<node>/proxy/stats/summary` — the native
kubelet primitive, no new mechanism) while a Job runs; observed peaks are
host-stamped into summary.json as resource_peaks, like patch_sha256. The
sampler must never affect the run it observes: fetch errors are counted,
never raised; no sample -> None, never a 0 masquerade.

Strict from birth (wave A precedent): the moved signatures were bare-class
debt inside k8s.py; at move time they are annotated (`dict` ->
`dict[str, Any]`, the fetch hook `Callable[[], dict[str, Any]] | None`, the
return types); bodies unchanged except the `json.loads` result, bound to an
annotated local (the gates.py:312 house pattern) to satisfy no-any-return.
Single home: k8s holds no def and no
re-export of these names; its two construction sites call
`peaks._ResourceSampler`, and the class resolves its helpers through this
module's globals — a test stub on a name here intercepts every call site.
_pod_of_job / _wait_job_terminal / _stream_pod_logs / _fresh_job stay in k8s
(Pod lifecycle observation machinery — a later portion). Guard:
test_peaks_facade.py (RED-calibrated). Acceptance: behavioral reference
byte-identical (evidence/waveA-ref-* recipe: run with a nonexistent ticket
-> rc=13).
"""

import json
import threading
from typing import Any, Callable

from launcher import kube

# ==================================================================================
# Resource sampling (operator decision 2026-10-16): the G1 requests/limits
# (bb5eed6) were committed as "pending measured peaks" — this closes the
# measurement half. Read-only polling of the kubelet stats API (`kubectl get
# --raw /api/v1/nodes/<node>/proxy/stats/summary` — the native kubelet
# primitive, no new mechanism) while a Job runs; observed peaks are
# host-stamped into summary.json as resource_peaks, like patch_sha256.
# gVisor caveat (BL-4 finding): under runsc the Pod's host cgroup IS the
# sandbox process (guest memory = host anonymous memory), so pod-level numbers
# are host-real; per-container accounting under runsc can drift. Peaks are
# published as OBSERVED kubelet numbers, never as truth claims; None when no
# sample succeeded (never a 0 masquerade).
# ==================================================================================
SAMPLE_INTERVAL_S = 10.0


def _node_of_pod(pod: str, ns: str) -> str | None:
    r = kube._kubectl("get", "pod", pod, "-n", ns, "-o", "jsonpath={.spec.nodeName}")
    node = (r.stdout or "").strip()
    return node or None


def _kubelet_stats(node: str) -> dict[str, Any]:
    r = kube._kubectl_checked("get", "--raw",
                        f"/api/v1/nodes/{node}/proxy/stats/summary")
    stats: dict[str, Any] = json.loads(r.stdout)
    return stats


def _peak_from_stats(stats: dict[str, Any], pod: str, ns: str
                     ) -> dict[str, Any] | None:
    """Pure extraction: the Pod's typed peak record from one kubelet summary,
    or None when the Pod is not in it."""
    for p in stats.get("pods", []):
        ref = p.get("podRef") or {}
        if ref.get("name") != pod or ref.get("namespace") != ns:
            continue
        mem = p.get("memory") or {}
        cpu = p.get("cpu") or {}
        return {
            "cpu_peak_nanocores": cpu.get("usageNanoCores"),
            "mem_peak_usage_bytes": mem.get("usageBytes"),
            "mem_peak_working_set_bytes": mem.get("workingSetBytes"),
        }
    return None


class _ResourceSampler(threading.Thread):
    """Samples kubelet stats for one Pod every interval until stopped, keeping
    the observed maxima. A fetch error is counted, never fatal — the sampler
    must never affect the run it observes."""

    def __init__(self, pod: str, ns: str, interval_s: float = SAMPLE_INTERVAL_S,
                 fetch: Callable[[], dict[str, Any]] | None = None) -> None:
        super().__init__(daemon=True)
        self.pod, self.ns, self.interval_s = pod, ns, interval_s
        self._fetch: Callable[[], dict[str, Any]] = fetch or self._default_fetch
        # NOT "_stop": CPython 3.11 Thread._wait_for_tstate_lock calls
        # self._stop() at join() — an Event attribute there shadows the
        # internal and join() raises TypeError (external review 2026-10-16,
        # reproduced on 3.11.15; the host venv is 3.13, so only a 3.11
        # launcher hits it — pinned by test_py311_join_contract).
        self._stop_event = threading.Event()
        self.samples = 0
        self.errors = 0
        self._peak: dict[str, Any] | None = None

    def _default_fetch(self) -> dict[str, Any]:
        node = _node_of_pod(self.pod, self.ns)
        if node is None:
            raise RuntimeError(f"pod {self.pod}: nodeName unavailable")
        return _kubelet_stats(node)

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                peak = _peak_from_stats(self._fetch(), self.pod, self.ns)
                if peak is not None:
                    self.samples += 1
                    self._merge(peak)
            except Exception:
                self.errors += 1
            self._stop_event.wait(self.interval_s)

    def _merge(self, peak: dict[str, Any]) -> None:
        if self._peak is None:
            self._peak = dict(peak)
            return
        for key in ("cpu_peak_nanocores", "mem_peak_usage_bytes",
                    "mem_peak_working_set_bytes"):
            cur, new = self._peak.get(key), peak.get(key)
            if new is not None:
                self._peak[key] = new if cur is None else max(cur, new)

    def stop_and_peaks(self) -> dict[str, Any] | None:
        """Stop sampling, return the typed record (peaks + samples/errors), or
        None when nothing was ever observed (never a 0 masquerade)."""
        self._stop_event.set()
        self.join(timeout=2 * self.interval_s + 5)
        if self.samples == 0:
            return None
        out = dict(self._peak or {})  # samples > 0 means _peak was set by _merge
        out["samples"] = self.samples
        out["errors"] = self.errors
        return out
