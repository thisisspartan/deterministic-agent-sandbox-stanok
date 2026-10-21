"""Unified launch preflight (operator spec 2026-10-12) — every check mocked.

The preflight turns the mid-run infrastructure failure classes observed in
this project into a pre-launch ENV-FAIL (rc=16) with the fix named:
  disk >= 80%          -> the cc248 kubelet-GC ImagePullBackOff precedent
  image label != digest of the current tree -> a stale entrypoint would run
  Opik unreachable     -> OTLP silently drops spans mid-run
  runtimeclass missing -> the Pod would die mid-run on a name typo
  netpol boundary absent in the Job namespace -> the worker would run with no
    egress restriction, the fresh Pod not deny-all (external review 2026-10-16)
  dangling stanok Jobs/Pods -> leftovers of a crashed run collide
Each check is tested in isolation with fakes (no real cluster, no real
docker, no real network); _preflight composition (host-side checks run
before cluster-side, first reason wins) is tested with mocked check
functions. The host_launch_k8s wiring (abort rc=16 before any cluster
call) lives in test_k8s_wiring.py.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_preflight.py -q
"""
import urllib.error

from launcher import k8s, kube, preflight
from launcher.config import Config


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _cfg(tmp_path, **kw):
    return Config(repo_root=str(tmp_path), log_dir=str(tmp_path / "logs"), **kw)


# --- disk guard (the cc248 GC incident fired at 85%) ------------------------------

def _fake_df(monkeypatch, *, rc=0, out):
    def fake_run(argv, **k):
        assert argv[:2] == ["df", "--output=pcent"], argv
        return _FakeCompleted(rc, out)
    monkeypatch.setattr(k8s.subprocess, "run", fake_run)


def test_disk_below_limit_is_none(tmp_path, monkeypatch):
    _fake_df(monkeypatch, out="Use%\n 79%\n")
    assert preflight._preflight_disk(_cfg(tmp_path)) is None


def test_disk_at_limit_is_reason_naming_the_fix(tmp_path, monkeypatch):
    _fake_df(monkeypatch, out="Use%\n 85%\n")
    reason = preflight._preflight_disk(_cfg(tmp_path))
    assert reason and "85%" in reason and "80%" in reason
    assert "images prune" in reason  # the named fix


def test_disk_unmeasurable_is_infra_reason(tmp_path, monkeypatch):
    _fake_df(monkeypatch, rc=1, out="")
    reason = preflight._preflight_disk(_cfg(tmp_path))
    assert reason and "cannot measure disk" in reason


# --- image staleness (stanok.digest LABEL vs the current tree) -------------------

def _fake_image_inspect(monkeypatch, *, rc=0, label=""):
    seen = []

    def fake_run(argv, **k):
        assert argv[0] == "docker" and argv[1] == "inspect", argv
        seen.append(argv)
        return _FakeCompleted(rc, label)
    monkeypatch.setattr(k8s.subprocess, "run", fake_run)
    monkeypatch.setattr(k8s.gates, "_image_digest", lambda cfg: "want-digest")
    return seen


def test_image_label_match_is_none(tmp_path, monkeypatch):
    _fake_image_inspect(monkeypatch, label="want-digest\n")
    assert preflight._preflight_image_label(_cfg(tmp_path)) is None


def test_image_label_mismatch_names_rebuild(tmp_path, monkeypatch):
    _fake_image_inspect(monkeypatch, label="old-digest")
    reason = preflight._preflight_image_label(_cfg(tmp_path))
    assert reason and "stale" in reason and "./setup.sh" in reason


def test_image_absent_names_build(tmp_path, monkeypatch):
    _fake_image_inspect(monkeypatch, rc=1)
    reason = preflight._preflight_image_label(_cfg(tmp_path))
    assert reason and "not found locally" in reason and "setup.sh" in reason


# --- Opik reachability (tracing is ON by default) ---------------------------------

class _FakeOpener:
    def __init__(self, exc):
        self.exc = exc
        self.urls = []

    def open(self, req, timeout=None):
        self.urls.append(req.full_url)
        if self.exc:
            raise self.exc
        return _FakeCompleted(0)


def _fake_opik(monkeypatch, exc):
    opener = _FakeOpener(exc)
    monkeypatch.setattr(preflight.urllib.request, "build_opener", lambda *a: opener)
    return opener


def test_opik_empty_url_skips_the_check(tmp_path, monkeypatch):
    opener = _fake_opik(monkeypatch, urllib.error.URLError("boom"))
    assert preflight._preflight_opik(_cfg(tmp_path, opik_trace_url="")) is None
    assert opener.urls == []  # tracing explicitly off -> no probe


def test_opik_unreachable_is_reason_naming_the_fix(tmp_path, monkeypatch):
    _fake_opik(monkeypatch, urllib.error.URLError("connection refused"))
    reason = preflight._preflight_opik(
        _cfg(tmp_path, opik_trace_url="http://192.168.122.156:8080/v1/private/otel"))
    assert reason and "Opik unreachable" in reason
    assert "STANOK_OPIK_TRACE_URL" in reason  # the named escape hatch


def test_opik_http_answer_even_error_is_reachable(tmp_path, monkeypatch):
    # any HTTP answer (405 on HEAD) proves the endpoint is up — OTLP will connect
    _fake_opik(monkeypatch, urllib.error.HTTPError("u", 405, "Method Not Allowed", {}, None))
    assert preflight._preflight_opik(
        _cfg(tmp_path, opik_trace_url="http://192.168.122.156:8080/v1/private/otel")) is None


# --- RuntimeClass existence (default gvisor, CC-256; runc opt-out skips) ---------

def test_runtimeclass_default_gvisor_is_checked(monkeypatch):
    # CC-256: unset -> the effective class is gvisor -> the check RUNS.
    monkeypatch.delenv("STANOK_K8S_RUNTIME_CLASS", raising=False)
    calls = []
    monkeypatch.setattr(kube, "_kubectl",
                        lambda *a, **k: calls.append(a) or _FakeCompleted(0, "gvisor"))
    assert preflight._preflight_runtime_class(None) is None
    assert calls and calls[0][:2] == ("get", "runtimeclass") and calls[0][2] == "gvisor"


def test_runtimeclass_runc_optout_skips_the_check(monkeypatch):
    monkeypatch.setenv("STANOK_K8S_RUNTIME_CLASS", "runc")
    calls = []
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: calls.append(a) or _FakeCompleted(0))
    assert preflight._preflight_runtime_class(None) is None
    assert calls == []


def test_runtimeclass_missing_is_reason(monkeypatch):
    monkeypatch.setenv("STANOK_K8S_RUNTIME_CLASS", "gvisor")
    seen = []

    def fake(*a, **k):
        seen.append(a)
        return _FakeCompleted(1, "", "not found")
    monkeypatch.setattr(kube, "_kubectl", fake)
    reason = preflight._preflight_runtime_class(None)
    assert reason and "runtimeclass 'gvisor' not in the cluster" in reason
    assert seen and seen[0][:2] == ("get", "runtimeclass")


def test_runtimeclass_present_is_none(monkeypatch):
    monkeypatch.setenv("STANOK_K8S_RUNTIME_CLASS", "gvisor")
    monkeypatch.setattr(kube, "_kubectl", lambda *a, **k: _FakeCompleted(0, "gvisor"))
    assert preflight._preflight_runtime_class(None) is None


# --- NetworkPolicy boundary (namespace-scoped, coverage by name prefix) -----------

def _fake_netpol(monkeypatch, *, rc=0, out=""):
    seen = []

    def fake(*a, **k):
        seen.append(a)
        return _FakeCompleted(rc, out, "boom" if rc else "")
    monkeypatch.setattr(kube, "_kubectl", fake)
    return seen


def test_netpol_present_any_revision_is_none(monkeypatch):
    # Coverage by NAME PREFIX, any revision: make-before-break (Package 1)
    # means an older revision may legitimately be the applied one — presence
    # of the boundary is the contract, never revision match.
    _fake_netpol(monkeypatch, out="stanok-worker-egress-d662f083ea71 "
                                  "stanok-fresh-deny-all-000000000000")
    assert preflight._preflight_netpol(None) is None


def test_netpol_check_is_namespace_scoped(monkeypatch):
    # A policy in another namespace does not select these Pods: the check
    # lists the namespace the Jobs render into (STANOK_K8S_NAMESPACE).
    monkeypatch.setenv("STANOK_K8S_NAMESPACE", "stanok-jobs")
    seen = _fake_netpol(monkeypatch, out="")
    reason = preflight._preflight_netpol(None)
    assert reason and "stanok-jobs" in reason and "netpol-smoke.sh" in reason
    assert seen and seen[0][:2] == ("get", "networkpolicy")
    assert seen[0][2:4] == ("-n", "stanok-jobs")


def test_netpol_missing_is_reason_naming_the_fix(monkeypatch):
    monkeypatch.delenv("STANOK_K8S_NAMESPACE", raising=False)
    _fake_netpol(monkeypatch, out="foreign-policy")
    reason = preflight._preflight_netpol(None)
    assert reason and "stanok-worker-egress-" in reason \
        and "stanok-fresh-deny-all-" in reason
    assert "default" in reason and "netpol-smoke.sh" in reason  # named fix


def test_netpol_partial_coverage_names_only_the_missing(monkeypatch):
    # worker boundary present, fresh deny-all absent -> still a defect, and
    # the reason names only what is missing
    _fake_netpol(monkeypatch, out="stanok-worker-egress-abc123def456")
    reason = preflight._preflight_netpol(None)
    assert reason and "stanok-fresh-deny-all-" in reason
    assert "stanok-worker-egress-" not in reason


def test_netpol_list_failure_is_infra_reason(monkeypatch):
    _fake_netpol(monkeypatch, rc=1)
    reason = preflight._preflight_netpol(None)
    assert reason and "cannot list NetworkPolicies" in reason


# --- dangling stanok Jobs/Pods -----------------------------------------------------

def _fake_kubectl(monkeypatch, *, jobs_out="", pods_out="", rc=0):
    seen = []

    def fake(*a, **k):
        seen.append(a)
        if "jobs" in a:
            return _FakeCompleted(rc, jobs_out)
        return _FakeCompleted(rc, pods_out)
    monkeypatch.setattr(kube, "_kubectl", fake)
    return seen


def test_dangling_none_is_none(monkeypatch):
    _fake_kubectl(monkeypatch)
    assert preflight._preflight_dangling(None) is None


def test_finished_resources_are_not_dangling(monkeypatch):
    # active=0 Job (awaiting its TTL) and a Succeeded Pod are inert — not dangling
    _fake_kubectl(monkeypatch,
                  jobs_out="stanok-job-old 0\n",
                  pods_out="stanok-pod-old Succeeded\n")
    assert preflight._preflight_dangling(None) is None


def test_active_job_and_running_pod_are_dangling(monkeypatch):
    _fake_kubectl(monkeypatch,
                  jobs_out="stanok-job-crash 1\nstanok-job-old 0\n",
                  pods_out="stanok-pod-crash Running\nstanok-pod-old Succeeded\n")
    reason = preflight._preflight_dangling(None)
    assert reason and "job/stanok-job-crash" in reason and "pod/stanok-pod-crash" in reason
    assert "stanok-job-old" not in reason and "stanok-pod-old" not in reason
    assert "launch.sh stop" in reason  # the named fix


def test_dangling_list_failure_is_infra_reason(monkeypatch):
    _fake_kubectl(monkeypatch, rc=1)
    reason = preflight._preflight_dangling(None)
    assert reason and "cannot list stanok Jobs" in reason


# --- _preflight composition: host-side first, first reason wins -------------------

def _mock_checks(monkeypatch, results):
    order = []

    def make(name):
        def check(cfg):
            order.append(name)
            return results.get(name)
        return check
    for name in ("_preflight_disk", "_preflight_image_label", "_preflight_opik",
                 "_preflight_cluster", "_preflight_runtime_class",
                 "_preflight_netpol", "_preflight_dangling"):
        monkeypatch.setattr(preflight, name, make(name.lstrip("_")))
    return order


def test_preflight_all_clean_is_none(monkeypatch):
    order = _mock_checks(monkeypatch, {})
    assert preflight._preflight(None) is None
    # the documented order: cheap host-side checks before the cluster checks
    assert order == ["preflight_disk", "preflight_image_label", "preflight_opik",
                     "preflight_cluster", "preflight_runtime_class",
                     "preflight_netpol", "preflight_dangling"]


def test_preflight_first_reason_wins_and_stops(monkeypatch):
    order = _mock_checks(monkeypatch, {"preflight_image_label": "image stale",
                                       "preflight_dangling": "dangling"})
    assert preflight._preflight(None) == "image stale"
    # the cluster checks never ran — the abort is already decided
    assert order == ["preflight_disk", "preflight_image_label"]
