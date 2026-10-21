"""lifecycle — the Pod/Job lifecycle observation cluster (wave A portion 6,
2026-10-21; names and bodies moved VERBATIM from launcher/k8s.py).

What moved: the observation helpers the host runs against a live Job —
_pod_of_job, _pod_image_id, _stream_pod_logs, _job_rc_and_tail,
_pod_infra_cause, _job_infra_cause, _wait_job_terminal — together with the
two post-deadline observation graces (_STREAM_GRACE_S, _TERMINAL_GRACE_S)
and the shared-end window calculator _observation_timeout that bounds the
worker observation chain. What stayed in k8s: the Job CONSTRUCTION policy
these windows are measured against — _DEADLINE_MARGIN_S and job_deadline
(activeDeadlineSeconds belongs to Job creation) — and _fresh_job/_image_ref
(fresh-check and image transport).

Strict from birth (wave A precedent): the missing return annotations
(_pod_of_job, _pod_image_id, _pod_infra_cause, _job_infra_cause), the
unannotated pod params and the bare `tuple` return (_job_rc_and_tail ->
tuple[int, str]) were annotated AT move time; bodies unchanged except two
typed locals in _wait_job_terminal (the gates.py:312 house pattern): the
json.loads result bound to an annotated local and the Job condition type
read through a typed local, so the `-> str` never returns Any.

Single home: k8s holds no def, no constant and no re-export of these names;
its two call-site clusters (host_launch_k8s, _fresh_job) call lifecycle._X,
and every test stub was re-bound to this module — a stub here intercepts
every call site (portion-2 precedent: setattrs on the SHARED module objects
kube._kubectl / kube._cluster_env / the time module stay). Guard:
test_lifecycle_facade.py (RED-calibrated). Acceptance: behavioral reference
byte-identical (evidence/waveA-ref-* recipe: run with a nonexistent ticket
-> rc=13).
"""

import json
import re
import subprocess
import time
from typing import Any

from launcher import kube
from launcher.logs import log


def _pod_of_job(job_name: str, ns: str, timeout_s: int = 120) -> str | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = kube._kubectl("get", "pods", "-n", ns, "-l", f"job-name={job_name}",
                     "-o", "jsonpath={.items[0].metadata.name}")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        time.sleep(2)
    return None


def _pod_image_id(pod: str | None, ns: str) -> str | None:
    """Image provenance (operator plan 2026-10-12): the image ID the runtime
    recorded for THIS run's Pod — `status.containerStatuses[0].imageID`, the
    kubelet/CRI's own record, not the host docker store's idea of the image.
    A content-addressed image ID is identical across runtimes, so this is the
    digest of the image the Job actually ran. Two runtime forms are valid:
    docker reports a bare "sha256:<hex>"; containerd/k3s (the DEFAULT runtime,
    live verify-registry run 2026-10-12) reports "<repo>@sha256:<hex>" — the
    registry-qualified form is the stronger proof (it names the registry the
    kubelet pulled from). Fail-soft: no pod, kubectl error, or a value whose
    tail is not a sha256 digest -> None (explicit, like commit_sha — never a
    guess)."""
    if not pod:
        return None
    r = kube._kubectl("get", "pod", pod, "-n", ns, "-o",
                 "jsonpath={.status.containerStatuses[0].imageID}")
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not re.search(r"(?:^|@)sha256:[0-9a-f]+$", out):
        return None
    return out


def _stream_pod_logs(pod: str, ns: str, path: str, timeout_s: int) -> bool:
    """kubectl logs -f blocks until the Pod's containers exit — the payload
    lands in the host-side log file, never in the supervisor's context.

    A2 (review 2026-10-17): the kubectl exit code is checked — a failed
    stream is reported as a stream failure, never conflated with "the Pod
    produced no logs"; the caller names it in the missing-payload abort."""
    with open(path, "wb") as lf:
        try:
            # CC-232: same config resolution as kube._kubectl — the log stream is
            # a kubectl call too (incident cc233: without it the stream died
            # on the non-readable /etc/rancher/k3s/k3s.yaml fallback).
            r = subprocess.run([kube._kubectl_bin(), "logs", "-f", pod, "-n", ns],
                               stdout=lf, stderr=subprocess.STDOUT,
                               timeout=timeout_s, env=kube._cluster_env())
        except subprocess.TimeoutExpired:
            log("K8S: kubectl logs -f hit the host timeout")
            return False
        except OSError as e:
            log(f"K8S: kubectl logs failed: {e}")
            return False
        if r.returncode != 0:
            log(f"K8S: kubectl logs -f exited rc={r.returncode} — log stream "
                f"failed, {path} may be incomplete")
            return False
    return True


def _job_rc_and_tail(job_name: str, ns: str) -> tuple[int, str]:
    """(exit_rc, tail) of a FAILED Job: the Pod's terminated exit code plus
    its log tail (the fresh-check failure text)."""
    exit_rc = 1
    p = kube._kubectl("get", "pods", "-n", ns, "-l", f"job-name={job_name}",
                 "-o", "jsonpath={.items[0].status.containerStatuses[0]."
                       "state.terminated.exitCode}")
    if p.returncode == 0 and p.stdout.strip().lstrip("-").isdigit():
        exit_rc = int(p.stdout.strip())
    pod = _pod_of_job(job_name, ns, timeout_s=30)
    tail = ""
    if pod:
        lg = kube._kubectl("logs", pod, "-n", ns)
        tail = (lg.stderr or "") + "\n" + (lg.stdout or "")
    return exit_rc, tail


def _pod_infra_cause(pod: str | None, ns: str) -> str | None:
    """BL-4 (a1/a2): classify a Pod death as an infrastructure cause.
    The gap _wait_job_terminal leaves: Job-level conditions say only
    'Failed', the Pod's own status says WHY. Two causes are infrastructure
    (rc=16, the 3 ticket retries are not burned on it):
      - containerStatuses[].state.terminated.reason == "OOMKilled" — the
        cgroup OOM kill. Measured 2026-10-16 (two gVisor probes at worker
        limits): kubelet reports it honestly under gVisor too — the Pod-slice
        limit is enforced, the overshoot is swap-absorbed until the swap is
        exhausted, then the sandbox is OOM-killed and the reason appears.
      - status.reason == "Evicted" — kubelet eviction.
    A bare exit 137 with NO reason is NOT OOM: the Job's
    activeDeadlineSeconds kill is also a SIGKILL (job_deadline). Anything
    else (a test failure) stays None — a ticket defect.
    Fail-soft: no pod / kubectl error / unparseable JSON -> None."""
    if not pod:
        return None
    r = kube._kubectl("get", "pod", pod, "-n", ns, "-o", "json")
    if r.returncode != 0:
        return None
    try:
        status = json.loads(r.stdout).get("status", {})
    except json.JSONDecodeError:
        return None
    for cs in status.get("containerStatuses") or []:
        term = (cs.get("state") or {}).get("terminated") or {}
        if term.get("reason") == "OOMKilled":
            return "OOMKilled"
    if status.get("reason") == "Evicted":
        return "Evicted"
    return None


def _job_infra_cause(name: str, ns: str) -> str | None:
    """Deadline contract (external review 2026-10-16): a Job killed by its
    own activeDeadlineSeconds reports Job condition Failed with
    reason="DeadlineExceeded". The Pod side shows only a bare SIGKILL
    (137, no reason), which _pod_infra_cause deliberately refuses to guess
    — the Job-level reason is the honest signal. Infrastructure defect:
    the session outlived the Job deadline, not a ticket defect.
    Fail-soft: no job / kubectl error / unparseable JSON -> None."""
    r = kube._kubectl("get", "job", name, "-n", ns, "-o", "json")
    if r.returncode != 0:
        return None
    try:
        conds = json.loads(r.stdout).get("status", {}).get("conditions", [])
    except json.JSONDecodeError:
        return None
    for c in conds:
        if (c.get("type") == "Failed" and c.get("status") == "True"
                and c.get("reason") == "DeadlineExceeded"):
            return "DeadlineExceeded"
    return None


def _wait_job_terminal(name: str, ns: str, timeout_s: int) -> str:
    """Poll the Job until a terminal condition: 'complete' | 'failed' | 'timeout'.
    `kubectl wait --for=condition=complete` blocks for the WHOLE timeout when the
    Job FAILED (live cc221, 2026-10-10: a failed fresh Job hung the host for an
    hour) — the host must learn about a failed Job immediately."""
    deadline = time.monotonic() + timeout_s
    while True:
        r = kube._kubectl("get", "job", name, "-n", ns, "-o", "json")
        if r.returncode == 0:
            try:
                # Strict-from-birth typed locals (the gates.py:312 house
                # pattern): the json.loads result and the condition type are
                # bound so the declared `-> str` never returns Any. Values and
                # flow are the originals — c.get("type") may legitimately be
                # None; the typed local is a checker annotation, not a
                # behavior change.
                job_json: dict[str, Any] = json.loads(r.stdout)
                conds: list[Any] = job_json.get("status", {}).get("conditions", [])
            except json.JSONDecodeError:
                conds = []
            for c in conds:
                ctype: str = c.get("type")
                if c.get("status") == "True" and ctype in ("Complete", "Failed"):
                    return ctype.lower()
        if time.monotonic() >= deadline:
            return "timeout"
        time.sleep(5)


# A3 (review 2026-10-17): the post-deadline observation graces, named. The
# host keeps watching past the Job's own activeDeadlineSeconds so it can
# still read the Pod's logs and the Job's terminal condition after the Pod
# self-terminates. The WORKER observation chain (job_deadline + stream
# grace + terminal grace, all sharing one absolute end anchored at Job
# creation) must stay under the supervisor's wait cap (cli.WAIT_TIMEOUT_S)
# — test_timer_contract pins the SUM, not just the deadline stage.
# Honest whole-run note (A3 doc honesty, review 2026-10-17): the cap
# bounds the worker chain (2340 < 2700), NOT the whole run. The fresh
# check runs after it: _fresh_job waits deadline + _TERMINAL_GRACE_S
# (2160) after up to two 30 s Pod lookups (_pod_of_job calls inside
# _fresh_job) — a whole run can reach at least 4530 s, past the 2700 s
# cap. Consequence if that happens: the supervisor hits rc=124
# (45-min cap) -> `launch.sh status` -> `launch.sh stop` (SIGTERM);
# finally removes only the resources the run created; the patch is NOT
# applied. Reconsideration
# trigger: the first real run that hits the cap during the fresh phase.
_STREAM_GRACE_S = 180
_TERMINAL_GRACE_S = 60


def _observation_timeout(obs_start: float, deadline: int, grace_s: int) -> int:
    """A3 fix (external review 2026-10-17): _stream_pod_logs and
    _wait_job_terminal take a DURATION measured from the call, so fresh
    durations handed to the two sequential worker-path calls could reach
    (deadline+180)+(deadline+60)=4440 — past the supervisor's wait cap.
    Both windows instead share ONE absolute end point measured from
    obs_start (Job creation): a call gets only the time remaining to
    obs_start + deadline + grace_s. Worst case for the worker observation
    chain from Job creation is then deadline + _STREAM_GRACE_S +
    _TERMINAL_GRACE_S = 2340 < cap (the whole run, fresh check included,
    can exceed the cap — see the constants-block note). Call this
    at each call site, never precompute — the remaining time is what bounds
    the chain."""
    return max(0, int(obs_start + deadline + grace_s - time.monotonic()))
