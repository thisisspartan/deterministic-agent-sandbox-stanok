"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §7/§9) — the manifests.

Vanilla-K8s manifests in stanok/k8s/ (no k3s-specific hacks). Structural
checks (no YAML parser in the image — the checks are text invariants):
  1  networkpolicy.yaml.tmpl (2.4 + Package 1, operator spec 2026-10-10):
     carries NO addresses — only the {{MODEL_IP}}/{{OPIK_HOST_IP}}/
     {{OPIK_BACKEND_IP}} placeholders (a dotted IPv4 literal in the
     template is a defect) plus {{NAMESPACE}} — the effective Job namespace
     from STANOK_K8S_NAMESPACE, the SAME knob the Job templates render
     (external review 2026-10-16: a hardcoded default left the boundary in
     the wrong namespace whenever the knob was set); rendered via launcher.netpol it gives worker
     egress ONLY to the model host:8080 and the Opik endpoints:8080 —
     NO kube-dns rule (full DNS egress blackout: the endpoints are IP
     literals in the Job env); the fresh Pod is default-deny in BOTH
     directions (policyTypes Ingress + Egress, no allow rules); names are
     versioned {{REVISION}} (deterministic, non-self-referential — pinned
     by test_revision_deterministic_and_non_self_referential below);
     model_ip() fails closed on a non-IPv4 STANOK_SERVER_URL host
  2  worker-job.yaml.tmpl: non-root hardening (runAsNonRoot,
     allowPrivilegeEscalation false, capabilities drop ALL, seccomp
     RuntimeDefault), activeDeadlineSeconds, the nonce/label placeholders,
     NO privileged; disk bound (Package 1): emptyDir sizeLimit 2Gi +
     ephemeral-storage requests/limits NOT equal to the volume size
     (the limit counts writable layer + emptyDir + logs together)
  3  fresh-job.yaml.tmpl: verifier only (run.sh list + test --all), the
     patch applied behind an explicit guard — a failed git apply exits with
     {{APPLY_FAIL_RC}} BEFORE any test runs (C3, review 2026-10-17), NO
     model address (deny-all Pod), the same disk bound
  4  CC-229 (SPEC-READONLY-ROOT-2026-10-10): readOnlyRootFilesystem: true
     in BOTH job templates (all Pod writes already target the /stanok-work
     emptyDir — HOME/TMPDIR re-redirected by pod_runner.py)
  5  CC-230: pod_runner.py consumes the nonce via os.environ.pop and drops
     it from the session env (the agent's Bash must not see $STANOK_NONCE);
     the fresh Job's HOME/TMPDIR point into the /stanok-work emptyDir (the
     read-only root makes the image default /home/stanok unwritable)
  6  CC-230 (operator spec 2026-10-10) + deadline contract (external review
     2026-10-16): Job timeouts — ttlSecondsAfterFinished 300 in BOTH
     templates (auto-cleanup); activeDeadlineSeconds rendered from
     job_deadline(cfg), default turn_timeout_s + startup margin (the Job
     must outlive the turn timer); env override STANOK_K8S_JOB_DEADLINE_S
  7  CC-234 (operator spec 2026-10-11): writable /tmp — an emptyDir tmp-dir
     (512Mi) mounted at /tmp in BOTH job templates (the CLI Bash tool
     mkdirs (CLAUDE_CODE_TMPDIR||/tmp)/claude-<uid>; a read-only /tmp
     killed every Bash call, traces cc231/cc233); pod_runner.py sets
     CLAUDE_CODE_TMPDIR (the name the CLI actually reads), never the old
     CLAUDE_TMPDIR
  8  CC-236 (incident cc235): CLAUDE_PROJECT_DIR=/stanok-work/repo in the
     worker Job env and in the pod_runner session env (the CLI does not
     export it for hooks; the PreToolUse command in .claude/settings.json
     references it — unset it the hook dies with exit 127 on every call)
  9  SPEC-GVISOR-SPIKE-2026-10-12 + CC-256 (default switch): the DEFAULT
     runtime class is gvisor — unset/empty renders `runtimeClassName: gvisor`
     in BOTH job templates (the fresh check runs under the same class as the
     worker); STANOK_K8S_RUNTIME_CLASS=runc renders the {{RUNTIME_CLASS}} line
     empty (no runtimeClassName field == RuntimeDefault, the pre-gVisor
     behavior); any other value renders `runtimeClassName: <value>`
  10 G1 (SPEC-HOSTSIDE-WORKFLOW-2026-10-14): explicit CPU/RAM requests+limits
     in BOTH job templates (worker 500m/1Gi -> 1000m/2Gi; fresh 250m/512Mi ->
     500m/1Gi — the fresh Pod has no agent CLI); limits >= requests; the
     existing disk bound, deadline and securityContext are untouched
  11 PSA (SPEC-PSA-2026-10-14): namespace.yaml pins the PSA labels on the
     Job namespace — warn/audit/enforce=restricted. enforce was added by the
     operator's decision 2026-10-14 (dry-run of both Pods clean under enforce,
     negative control Forbidden) with this explicit test edit — same
     single-source convention as the G1 values
  12 Verdict cross-check (external review 2026-10-16): pod_runner.py captures
     the session subprocess's exit code and ships it in the payload as
     internal_rc.txt; the host compares it against summary.json's "rc"
     (cli.py writes both from the same value — a mismatch is
     verdict-substitution, rc=16; host side tested in test_k8s_wiring.py)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_manifests.py -q
"""
import re
from pathlib import Path

import pytest

from launcher import k8s, kube, netpol
from launcher.config import Config

K8S_DIR = Path(__file__).resolve().parents[2] / "k8s"


def _read(name):
    return (K8S_DIR / name).read_text(encoding="utf-8")


def test_networkpolicy_template_carries_no_addresses():
    y = _read("networkpolicy.yaml.tmpl")
    assert "kind: NetworkPolicy" in y
    for ph in ("{{MODEL_IP}}", "{{OPIK_HOST_IP}}", "{{OPIK_BACKEND_IP}}"):
        assert ph in y
    # 2.4: the addresses live in configuration, not in the manifest
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", y)


def _docs(text):
    """Policy documents with comment lines stripped — the structural
    assertions run on the spec text only (the header comments describe the
    policies and would otherwise leak words like 'Ingress' into a doc)."""
    docs = []
    for d in text.split("\n---\n"):
        if "kind: NetworkPolicy" in d:
            docs.append("\n".join(
                line for line in d.splitlines()
                if not line.lstrip().startswith("#")))
    return docs


def _worker_doc(text):
    return next(d for d in _docs(text) if "stanok: worker" in d)


def _fresh_doc(text):
    return next(d for d in _docs(text) if "stanok: fresh" in d)


def test_networkpolicy_worker_egress(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    y = netpol.render_netpol()
    assert "kind: NetworkPolicy" in y
    assert "192.168.8.131/32" in y
    assert "8080" in y
    # Package 1: full DNS egress blackout — NO kube-dns rule, no port 53
    # anywhere in the worker policy (the endpoints are IP literals).
    w = _worker_doc(y)
    assert "port: 53" not in w
    assert "kube-dns" not in w
    assert "kube-system" not in w
    # Egress-only: the worker policy carries no Ingress type.
    assert "Ingress" not in w
    # no placeholder survived the render
    assert "{{" not in y


def test_networkpolicy_fresh_deny_both_directions():
    y = _read("networkpolicy.yaml.tmpl")
    f = _fresh_doc(y)
    # Package 1: default-deny in BOTH directions — Ingress AND Egress in
    # policyTypes, and NO allow rules (no ingress:/egress: rule keys).
    assert "Ingress" in f
    assert "Egress" in f
    assert "ingress:" not in f
    assert "egress:" not in f


def test_netpol_model_ip_fail_closed(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://model.local:8080")
    with pytest.raises(ValueError):
        netpol.model_ip()


def test_netpol_defaults(monkeypatch):
    for var in ("STANOK_OPIK_HOST_IP", "STANOK_OPIK_BACKEND_IP",
                "STANOK_K8S_NAMESPACE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    v = netpol.netpol_variables()
    assert v["MODEL_IP"] == "192.168.8.131"
    assert v["NAMESPACE"] == "default"  # the STANOK_K8S_NAMESPACE default
    assert v["OPIK_HOST_IP"] == "192.168.122.156"
    assert v["OPIK_BACKEND_IP"] == "172.25.0.250"


def test_networkpolicy_namespace_follows_job_knob(monkeypatch):
    # External review 2026-10-16: the boundary must live where the Jobs run.
    # The template carries {{NAMESPACE}}; netpol_variables() supplies it from
    # kube._namespace() — the same knob worker/fresh-job.yaml.tmpl render.
    y = _read("networkpolicy.yaml.tmpl")
    assert y.count("namespace: {{NAMESPACE}}") == 2

    monkeypatch.delenv("STANOK_K8S_NAMESPACE", raising=False)
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    y_def, rev_def = netpol.render_netpol_with_revision()
    assert "namespace: default" in y_def and "{{" not in y_def

    monkeypatch.setenv("STANOK_K8S_NAMESPACE", "stanok-jobs")
    y_cust, rev_cust = netpol.render_netpol_with_revision()
    assert "namespace: stanok-jobs" in y_cust
    assert "namespace: default" not in y_cust and "{{" not in y_cust
    # the namespace line is canonical content: a different namespace is a
    # semantic change -> new revision -> new versioned object names
    assert rev_cust != rev_def


def test_worker_job_hardening():
    y = _read("worker-job.yaml.tmpl")
    assert "runAsNonRoot: true" in y
    assert "allowPrivilegeEscalation: false" in y
    assert "ALL" in y  # capabilities drop
    assert "RuntimeDefault" in y
    assert "activeDeadlineSeconds" in y
    assert "{{NONCE}}" in y
    assert "{{LABEL}}" in y
    assert "privileged: true" not in y


def test_fresh_job_verifier_only():
    y = _read("fresh-job.yaml.tmpl")
    assert "run.sh" in y
    assert "test --all" in y
    assert "changes.patch" in y
    assert "192.168.8.131" not in y  # deny-all Pod: no model endpoint


def test_fresh_job_apply_guard_exits_before_tests():
    # C3 (review 2026-10-17): the Pod's own git apply must not fail silently
    # into the test run — a result computed on an UNPATCHED tree must never
    # be reported as a test result. The guard exits with {{APPLY_FAIL_RC}}
    # (rendered from k8s.py FRESH_APPLY_FAIL_RC) before run.sh is invoked.
    y = _read("fresh-job.yaml.tmpl")
    assert "git apply /stanok/patch/changes.patch || {" in y
    assert "exit {{APPLY_FAIL_RC}}" in y
    # ordering: the guard precedes the run.sh pair (the command itself, not
    # the phrase — it also appears in the template's header comment)
    assert y.index("exit {{APPLY_FAIL_RC}}") < y.index("bash scripts/run.sh list")


def test_k8s_renders_apply_fail_rc_in_fresh_job():
    # Wiring: the fresh render dict passes APPLY_FAIL_RC from the single
    # source constant; the worker Job applies no patch, so exactly one. The
    # value 20 is pinned deliberately (disjoint from the run.sh rc table and
    # every runner code — asserted in test_fresh_apply_guard.py).
    src = (Path(__file__).resolve().parents[1] / "k8s.py").read_text(
        encoding="utf-8")
    assert src.count('"APPLY_FAIL_RC": str(FRESH_APPLY_FAIL_RC),') == 1
    assert "FRESH_APPLY_FAIL_RC = 20" in src


# --- Package 1 (operator spec 2026-10-10): versioned names + disk bound ---

def test_networkpolicy_template_carries_revision_placeholder():
    y = _read("networkpolicy.yaml.tmpl")
    assert "{{REVISION}}" in y
    # both policies are versioned
    assert "stanok-worker-egress-{{REVISION}}" in y
    assert "stanok-fresh-deny-all-{{REVISION}}" in y


# --- CC-229 (SPEC-READONLY-ROOT-2026-10-10): read-only root FS ----------

def test_worker_job_read_only_root():
    y = _read("worker-job.yaml.tmpl")
    assert "readOnlyRootFilesystem: true" in y


def test_fresh_job_read_only_root():
    y = _read("fresh-job.yaml.tmpl")
    assert "readOnlyRootFilesystem: true" in y


# --- CC-230: nonce isolation + fresh-Pod HOME/TMPDIR alignment ----------

def test_pod_runner_consumes_and_drops_nonce():
    src = (Path(__file__).resolve().parents[1] / "pod_runner.py").read_text(
        encoding="utf-8")
    assert 'os.environ.pop("STANOK_NONCE")' in src
    assert 'os.environ["STANOK_NONCE"]' not in src  # no leak back-read
    assert 'env.pop("STANOK_NONCE", None)' in src  # session-env belt


def test_fresh_job_home_tmpdir_aligned():
    y = _read("fresh-job.yaml.tmpl")
    assert "name: HOME" in y and "value: /stanok-work/home" in y
    assert "name: TMPDIR" in y and "value: /stanok-work/tmp" in y
    # the dirs must exist before the tests run (read-only root, emptyDir)
    assert "mkdir -p /stanok-work/work /stanok-work/home /stanok-work/tmp" in y


# --- CC-236 (incident cc235): CLAUDE_PROJECT_DIR for hooks ----------

def test_worker_job_exports_claude_project_dir():
    # The CLI does not export CLAUDE_PROJECT_DIR for hooks (cli.js 2.1.88,
    # plugin context only); the PreToolUse command in .claude/settings.json
    # references it — unset it expands to /.claude/hooks/... and every tool
    # call ends with a non-blocking hook error (exit 127), killing the loop
    # guard (trace cc235: num_non_blocking_error=1). The Job env must set it.
    y = _read("worker-job.yaml.tmpl")
    assert "name: CLAUDE_PROJECT_DIR" in y
    assert 'value: "/stanok-work/repo"' in y


def test_pod_runner_exports_claude_project_dir():
    # Belt: the runner sets it in the session env before the CLI starts.
    src = (Path(__file__).resolve().parents[1] / "pod_runner.py").read_text(
        encoding="utf-8")
    assert '"CLAUDE_PROJECT_DIR": REPO' in src


def test_pod_runner_ships_internal_rc():
    # Verdict cross-check (external review 2026-10-16): the session's own
    # exit code must travel in the payload — the host compares it against
    # summary.json's "rc" (the host-side comparison is tested in
    # test_k8s_wiring.py).
    src = (Path(__file__).resolve().parents[1] / "pod_runner.py").read_text(
        encoding="utf-8")
    assert "internal_rc = proc.returncode" in src
    assert '"internal_rc.txt": f"{internal_rc}\\n".encode("ascii")' in src


# --- CC-232: Pod-only test guard marker in both Pod templates ----------

def test_pod_templates_mark_in_pod():
    # tests/** guard Pod-only invariants behind STANOK_IN_POD; both Pods must
    # set it, or the fresh Job would skip the very tests it verifies.
    for name in ("worker-job.yaml.tmpl", "fresh-job.yaml.tmpl"):
        y = _read(name)
        assert "name: STANOK_IN_POD" in y, name
        assert 'value: "1"' in y, name


def test_job_timeouts():
    # CC-230: auto-cleanup in both templates; the deadline is rendered from
    # job_deadline() (never a literal in the template).
    for name in ("worker-job.yaml.tmpl", "fresh-job.yaml.tmpl"):
        y = _read(name)
        assert "ttlSecondsAfterFinished: 300" in y
        assert "activeDeadlineSeconds: {{DEADLINE}}" in y


def test_job_deadline_default_and_override(tmp_path, monkeypatch):
    # Deadline contract (external review 2026-10-16): the default must
    # STRICTLY exceed the turn timeout — the old 1800 == STANOK_TURN_TIMEOUT_S
    # meant the Job killed the Pod exactly when the turn timer would have
    # produced a clean verdict. The env override stays an explicit operator
    # knob (wins over the contract, no validation).
    monkeypatch.delenv("STANOK_K8S_JOB_DEADLINE_S", raising=False)
    cfg = Config(repo_root=str(tmp_path), log_dir=str(tmp_path / "logs"))
    d = k8s.job_deadline(cfg)
    assert d > cfg.turn_timeout_s
    assert d == int(cfg.turn_timeout_s) + k8s._DEADLINE_MARGIN_S
    monkeypatch.setenv("STANOK_K8S_JOB_DEADLINE_S", "600")
    assert k8s.job_deadline(cfg) == 600


def test_rendered_names_are_versioned(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    y, rev = netpol.render_netpol_with_revision()
    assert re.search(r"name: stanok-worker-egress-[0-9a-f]{12}$", y, re.M)
    assert re.search(r"name: stanok-fresh-deny-all-[0-9a-f]{12}$", y, re.M)
    # one revision for the whole manifest — both names carry it
    assert y.count(f"-{rev}") == 2
    assert "{{" not in y


def test_revision_deterministic_and_non_self_referential(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    _, r1 = netpol.render_netpol_with_revision()
    _, r2 = netpol.render_netpol_with_revision()
    assert r1 == r2  # same inputs -> same revision (make-before-break safe)

    # a semantic change (an egress port) -> a different revision
    orig = kube._read_manifest
    kube._read_manifest = lambda name: orig(name).replace("port: 8080",
                                                          "port: 9090")
    try:
        _, r3 = netpol.render_netpol_with_revision()
    finally:
        kube._read_manifest = orig
    assert r3 != r1

    # a NAME-only change -> the SAME revision (the hash never contains the
    # name it is used in — non-self-referential)
    kube._read_manifest = lambda name: orig(name).replace(
        "stanok-worker-egress-", "stanok-worker-egressX-")
    try:
        _, r4 = netpol.render_netpol_with_revision()
    finally:
        kube._read_manifest = orig
    assert r4 == r1


def test_job_disk_bounds():
    # Package 1: emptyDir sizeLimit + ephemeral-storage requests/limits —
    # and the limit must NOT equal the volume size (double-accounting:
    # the kubelet counts writable layer + emptyDir + /var/log/pods).
    for name in ("worker-job.yaml.tmpl", "fresh-job.yaml.tmpl"):
        y = _read(name)
        assert "sizeLimit: 2Gi" in y
        assert 'ephemeral-storage: "1Gi"' in y
        assert 'ephemeral-storage: "4Gi"' in y
        assert 'ephemeral-storage: "2Gi"' not in y


# --- G1 (SPEC-HOSTSIDE-WORKFLOW-2026-10-14): CPU/RAM bounds -----------------

def test_job_cpu_ram_bounds():
    # Explicit CPU/RAM requests+limits in BOTH templates; the fresh Pod is
    # lighter (no agent CLI). The values are the single source (same
    # convention as test_job_disk_bounds); refinement is a deliberate edit.
    expected = {
        "worker-job.yaml.tmpl": ("cpu: 500m", "cpu: 1000m",
                                 'memory: "1Gi"', 'memory: "2Gi"'),
        "fresh-job.yaml.tmpl": ("cpu: 250m", "cpu: 500m",
                                'memory: "512Mi"', 'memory: "1Gi"'),
    }
    for name, (cpu_req, cpu_lim, mem_req, mem_lim) in expected.items():
        y = _read(name)
        for needle in (cpu_req, cpu_lim, mem_req, mem_lim):
            assert needle in y, (name, needle)
        # exactly one resources block per template, keeping the disk bound
        # (values: test_job_disk_bounds)
        assert y.count("requests:") == 1 and y.count("limits:") == 1, name


# --- CC-234 (operator spec 2026-10-11): writable /tmp + the CLI env name ---

def test_job_templates_mount_tmp():
    # The CLI Bash tool mkdirs (CLAUDE_CODE_TMPDIR||/tmp)/claude-<uid>
    # (cli.js 2.1.88); under readOnlyRootFilesystem a read-only /tmp made
    # every Bash call die ENOENT (traces cc231/cc233). Both Pods get a
    # dedicated emptyDir at /tmp.
    for name in ("worker-job.yaml.tmpl", "fresh-job.yaml.tmpl"):
        y = _read(name)
        assert "name: tmp-dir" in y, name
        assert "mountPath: /tmp" in y, name
        assert "sizeLimit: 512Mi" in y, name


def test_pod_runner_sets_claude_code_tmpdir():
    src = (Path(__file__).resolve().parents[1] / "pod_runner.py").read_text(
        encoding="utf-8")
    # the name the CLI Bash tool actually reads (cli.js: CLAUDE_CODE_TMPDIR
    # || "/tmp"); the old CLAUDE_TMPDIR only reached the nested bwrap.
    assert '"CLAUDE_CODE_TMPDIR": tmp' in src
    assert '"CLAUDE_TMPDIR"' not in src


# --- SPEC-GVISOR-SPIKE-2026-10-12: runtime-class knob ----------------------

def test_runtime_class_default_and_knob(monkeypatch):
    # CC-256: unset/empty -> gvisor (the new default); runc -> "" (the
    # {{RUNTIME_CLASS}} line renders empty == RuntimeDefault, pre-gVisor);
    # any other value renders `runtimeClassName: <value>`.
    monkeypatch.delenv("STANOK_K8S_RUNTIME_CLASS", raising=False)
    assert k8s._runtime_class() == "runtimeClassName: gvisor"
    monkeypatch.setenv("STANOK_K8S_RUNTIME_CLASS", "")
    assert k8s._runtime_class() == "runtimeClassName: gvisor"
    monkeypatch.setenv("STANOK_K8S_RUNTIME_CLASS", "runc")
    assert k8s._runtime_class() == ""
    monkeypatch.setenv("STANOK_K8S_RUNTIME_CLASS", "gvisor")
    assert k8s._runtime_class() == "runtimeClassName: gvisor"


def test_job_templates_carry_runtime_class_placeholder():
    # Both Pods get the knob — the fresh check must run under the same
    # runtime class as the worker.
    for name in ("worker-job.yaml.tmpl", "fresh-job.yaml.tmpl"):
        y = _read(name)
        assert "{{RUNTIME_CLASS}}" in y, name


def test_k8s_renders_runtime_class_in_both_jobs():
    # Wiring: both render dicts (worker + fresh) pass RUNTIME_CLASS.
    src = (Path(__file__).resolve().parents[1] / "k8s.py").read_text(
        encoding="utf-8")
    assert src.count('"RUNTIME_CLASS": _runtime_class(),') == 2


# --- PSA (SPEC-PSA-2026-10-14): namespace labels ---------------------------

def test_namespace_yaml_psa_labels():
    # Stage 1 (host-side, 2026-10-14): warn/audit=restricted. Stage 2
    # (operator decision, 2026-10-14): enforce=restricted applied to the live
    # namespace AND to this manifest — the manifest now describes the applied
    # cluster state (the test edit was the explicit decision marker, same
    # convention as the G1 values).
    # structural assertions run on the manifest text with comment lines
    # stripped (same convention as _docs() above)
    y = "\n".join(line for line in _read("namespace.yaml").splitlines()
                  if not line.lstrip().startswith("#"))
    assert "kind: Namespace" in y
    assert "name: default" in y  # the STANOK_K8S_NAMESPACE default (k8s.py)
    assert "pod-security.kubernetes.io/warn: restricted" in y
    assert "pod-security.kubernetes.io/audit: restricted" in y
    assert "pod-security.kubernetes.io/enforce: restricted" in y


def test_job_templates_are_restricted_clean():
    # The profile choice (restricted) is only safe because both Pod templates
    # already satisfy it — pinned here so a future template edit cannot drift
    # into a profile violation. The fields below are the restricted-profile
    # requirements the templates must keep (the per-field detail is pinned by
    # test_worker_job_hardening / test_*_read_only_root above).
    for name in ("worker-job.yaml.tmpl", "fresh-job.yaml.tmpl"):
        y = _read(name)
        assert "runAsNonRoot: true" in y, name
        assert "allowPrivilegeEscalation: false" in y, name
        assert "drop:" in y and "- ALL" in y, name
        assert "type: RuntimeDefault" in y, name
        # restricted disallows hostPath volumes and hostPorts — neither may
        # ever appear in a stanok Pod.
        assert "hostPath" not in y, name
        assert "hostPort" not in y, name
        assert "privileged: true" not in y, name


# --- R5 (#311, operator order 2026-10-21): template value validation ------

def test_render_template_rejects_markup_injection():
    # render_template is plain str.replace — no escaping. A value carrying
    # "{{" chains a second substitution pass (manifest markup arriving
    # through the value: a placeholder injected via a placeholder); a value
    # carrying "\n" breaks YAML structure at the placeholder site. Both
    # must raise before the manifest reaches the cluster. Companion
    # positive: clean single-line values (the shape every real caller
    # supplies — sanitized names, model_ip()-validated IPs, hex revisions,
    # str() of ints) render exactly as before.
    with pytest.raises(ValueError):
        kube.render_template("value: {{V}}", {"V": "{{MODEL_IP}}"})
    with pytest.raises(ValueError):
        kube.render_template("value: {{V}}", {"V": "line1\nline2"})
    assert kube.render_template("image: {{IMAGE}}\nnamespace: {{NS}}", {
        "IMAGE": "img@sha256:0123abcd", "NS": "default"}) == (
        "image: img@sha256:0123abcd\nnamespace: default")
