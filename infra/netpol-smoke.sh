#!/usr/bin/env bash
# netpol-smoke.sh — repeatable network smoke for the K8s runtime
# (SPEC-STANOK-K8S-RUNTIME; re-runnable after every NetworkPolicy change).
#
# Package 1 (operator spec 2026-10-10) — what this script measures:
#  1. MAKE-BEFORE-BREAK CUTOVER. The rendered manifest carries versioned
#     names (stanok-worker-egress-<revision>, stanok-fresh-deny-all-
#     <revision>; the k3s netpol controller ignores UPDATES). NetworkPolicy
#     rules are ADDITIVE, so: capture the old Stanok-managed names, APPLY
#     the new ones first, verify them, and only then DELETE the older names
#     (legacy fixed names included). A failed apply keeps the old policies
#     (nothing was removed); a failed delete exits non-zero and reports the
#     lingering old permissions — a DNS blackout is claimed only after the
#     old worker policy is gone.
#  2. FULL DNS EGRESS BLACKOUT (worker). No kube-dns rule exists anymore:
#     bounded UDP/TCP-53 probes against the resolver from the Pod's
#     /etc/resolv.conf plus 1.1.1.1 — worker expects FAIL, the unlabeled
#     control Pod expects OK (positive control: the probe machinery works,
#     the block is the policy).
#  3. PAIRED SSH. control -> OPIK_HOST_IP:22 OK is the MANDATORY
#     precondition; only then is a worker FAIL on the same address+port
#     evidence of the policy, not of a dead SSH.
#  4. INGRESS. The fresh Pod is default-deny in BOTH directions: the probe
#     Pods listen on 8080, so control -> fresh-pod:8080 FAIL can only be
#     the policy (nothing-listening is excluded by the listener), and
#     control -> worker-pod:8080 OK proves the worker Pod is reachable.
#  5. HONEST COUNTING. The verdict line is strictly dynamic:
#     "N/N hard checks passed (<M> external checks SKIPPED, <K> INFO)" —
#     no rounding, no silent drops.
#
# Traps kept from the 2026-10-10 review:
#  - LABEL: the worker probe Pod carries the exact label the worker Job
#    carries; an unlabeled pod is NOT restricted (a green there proves
#    nothing) — it is the CONTROL, and its probes are expected OK.
#  - REAL ADDRESSES (2.4): the script renders the manifest (STANOK_SERVER_URL
#    REQUIRED) and derives probe targets from the RENDERED /32 cidrs. The
#    post-DNAT address (CC-225) is proven by the published-address probe;
#    a DIRECT probe of it is informational only (not routable from pods).
#  - HOST EXPOSURE: the external check runs ONLY when STANOK_LAN_PEER is
#    set; without a peer it is reported SKIP, never silently dropped.
#
# Evidence (evidence/netpol-<ts>/): results.txt, the applied manifest,
# sha256 of template + script + applied manifest, the applied versioned
# policy names + revision, the captured old names.
#
# Usage (on the k3s host):
#   KUBECONFIG=<kubeconfig> STANOK_SERVER_URL=http://<model-host>:8080 \
#     [STANOK_LAN_PEER=<ssh-host>] infra/netpol-smoke.sh
# Knobs: STANOK_PY (default <repo>/.venv/bin/python — the netpol renderer),
#        STANOK_KUBECTL (default kubectl), STANOK_NAMESPACE (default),
#        STANOK_IMAGE (default stanok-machine:latest — the image the Jobs use;
#        probe Pods pin imagePullPolicy: IfNotPresent, kubectl run would force
#        Always for :latest and fail with ErrImagePull).
# Exit: 0 = every hard check matched its expectation; 1 = a mismatch;
#       2 = preflight/cutover failed (cluster/image/apply — infrastructure).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECTL="${STANOK_KUBECTL:-kubectl}"
NS="${STANOK_NAMESPACE:-default}"
IMAGE="${STANOK_IMAGE:-stanok-machine:latest}"
TS="$(date +%F-%H%M%S)"
EV="$ROOT/evidence/netpol-$TS"
LOG="$EV/results.txt"
TEMPLATE="$ROOT/k8s/networkpolicy.yaml.tmpl"
APPLIED="$EV/networkpolicy.applied.yaml"
PY="${STANOK_PY:-$ROOT/.venv/bin/python}"
PODS=(netpol-probe-worker netpol-probe-control netpol-probe-fresh)

mkdir -p "$EV"
exec > >(tee "$LOG") 2>&1

die() { echo "FATAL: $*"; exit 2; }

# cleanup BEFORE any mutation (the pods are disposable; the policies are not)
cleanup() { "$KUBECTL" delete -n "$NS" --wait=false pod "${PODS[@]}" >/dev/null 2>&1; }
trap cleanup EXIT

# --- [1/6] preflight -------------------------------------------------------------
command -v "$KUBECTL" >/dev/null || die "kubectl not found"
"$KUBECTL" get nodes >/dev/null 2>&1 || die "cluster unreachable (kubectl get nodes)"
[[ -f "$TEMPLATE" ]] || die "template missing: $TEMPLATE"
[[ -x "$PY" ]] || die "renderer python missing: $PY"
[[ -n "${STANOK_SERVER_URL:-}" ]] || die "STANOK_SERVER_URL must be set (MODEL_IP is derived from it)"

echo "== netpol-smoke $TS (Package 1: make-before-break, DNS blackout, paired SSH, ingress) =="
echo "template sha256: $(sha256sum "$TEMPLATE" | cut -d' ' -f1)"

# --- [2/6] render; capture the OLD policy names BEFORE any mutation -------------
(cd "$ROOT" && "$PY" -m launcher.netpol) > "$APPLIED" || die "netpol render failed (launcher.netpol)"
echo "rendered: $APPLIED"
APPLIED_SHA="$(sha256sum "$APPLIED" | cut -d' ' -f1)"
echo "applied manifest sha256: $APPLIED_SHA"
sha256sum "$APPLIED" > "$EV/manifest.sha256"
sha256sum "$TEMPLATE" "${BASH_SOURCE[0]}" "$APPLIED" > "$EV/hashes.txt"
# Probe targets = the rendered manifest's three /32 cidrs, in template order
mapfile -t CIDRS < <(grep -oE 'cidr: [0-9.]+/32' "$APPLIED" | awk '{print $2}')
MODEL_IP="${CIDRS[0]%%/*}"; OPIK_HOST_IP="${CIDRS[1]%%/*}"; OPIK_BACKEND_IP="${CIDRS[2]%%/*}"
[[ -n "$MODEL_IP" && -n "$OPIK_HOST_IP" && -n "$OPIK_BACKEND_IP" ]] \
  || die "rendered manifest has fewer than 3 /32 cidrs"
REV="$(grep -oE 'name: stanok-worker-egress-[0-9a-f]+' "$APPLIED" | head -1 | sed 's/.*-//')"
[[ -n "$REV" ]] || die "rendered manifest carries no revision — versioned names broken"
NEW1="stanok-worker-egress-$REV"; NEW2="stanok-fresh-deny-all-$REV"
echo "targets: model=$MODEL_IP opik-host=$OPIK_HOST_IP opik-post-dnat=$OPIK_BACKEND_IP"
echo "revision: $REV — applying as: $NEW1 $NEW2"
mapfile -t OLD_POLICIES < <("$KUBECTL" get networkpolicy -n "$NS" -o name 2>/dev/null | grep -E '/stanok-' || true)
echo "old Stanok-managed policies captured: ${#OLD_POLICIES[@]} (${OLD_POLICIES[*]:-none})"

# --- [3/6] make-before-break cutover ---------------------------------------------
# APPLY the new names first (additive union: the old rules stay effective
# until the old objects are deleted — no permission gap, no rollback needed).
"$KUBECTL" apply -n "$NS" -f "$APPLIED" >/dev/null || die "netpol apply failed — old policies NOT removed (nothing was deleted)"
"$KUBECTL" get networkpolicy "$NEW1" "$NEW2" -n "$NS" >/dev/null \
  || die "applied policies not found after apply — cutover failed, old policies kept"
DELETE_FAILED=0
for p in "${OLD_POLICIES[@]:-}"; do
  [[ -z "$p" ]] && continue
  base="${p##*/}"
  [[ "$base" == "$NEW1" || "$base" == "$NEW2" ]] && continue
  if ! "$KUBECTL" delete -n "$NS" "$p" >/dev/null 2>&1; then
    echo "WARN: failed to delete $p — old permissions LINGER, DNS blackout cannot be claimed"
    DELETE_FAILED=1
  fi
done
echo "cutover: new applied, old deleted (delete_failed=$DELETE_FAILED)"

# --- [4/6] probe pods: worker-labeled, control (no label), fresh-labeled -------
# Each probe Pod listens on 8080: an ingress FAIL can then only be the
# policy — 'nothing listens there' is excluded by construction.
apply_pod() { # $1=name $2=stanok-label ("" = unlabeled control)
  local labels_block=""
  if [[ -n "$2" ]]; then
    labels_block="  labels:
    stanok: $2"
  fi
  "$KUBECTL" apply -n "$NS" -f - >/dev/null <<EOF || die "pod $1 create failed"
apiVersion: v1
kind: Pod
metadata:
  name: $1
  namespace: $NS
$labels_block
spec:
  restartPolicy: Never
  containers:
    - name: probe
      image: $IMAGE
      imagePullPolicy: IfNotPresent
      # Listener on :8080. Quoting chain (heredoc -> YAML -> bash -> python):
      # the YAML scalar is DOUBLE-quoted with \\" -> \" (heredoc eats one
      # backslash); the python code is shell-single-quoted and uses only
      # double quotes inside. A YAML single-quoted scalar here would eat
      # '' -> ' and break the python string (listener silently dead).
      command: ["bash", "-c", "python3 -c 'import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind((\\"\\"  , 8080)); s.listen(8); [s.accept() for _ in iter(int, 1)]' & sleep 900"]
EOF
  "$KUBECTL" wait --for=condition=Ready "pod/$1" -n "$NS" --timeout=120s >/dev/null \
    || die "pod $1 not Ready"
}
apply_pod netpol-probe-worker worker
apply_pod netpol-probe-control ""
apply_pod netpol-probe-fresh fresh
echo "probe pods Ready (listener on :8080)"

RESOLVER="$("$KUBECTL" exec -n "$NS" netpol-probe-worker -- sed -n 's/^nameserver \([0-9.]\{1,\}\).*/\1/p' /etc/resolv.conf 2>/dev/null | head -1)"
[[ -n "$RESOLVER" ]] || die "no nameserver in the probe Pod's /etc/resolv.conf"
WORKER_POD_IP="$("$KUBECTL" get pod netpol-probe-worker -n "$NS" -o jsonpath='{.status.podIP}')"
FRESH_POD_IP="$("$KUBECTL" get pod netpol-probe-fresh -n "$NS" -o jsonpath='{.status.podIP}')"
echo "resolver=$RESOLVER worker-pod-ip=$WORKER_POD_IP fresh-pod-ip=$FRESH_POD_IP"

# Probe primitives (defined BEFORE the convergence loop uses them).
probe_tcp() { # pod host port -> OK|FAIL
  "$KUBECTL" exec -n "$NS" "$1" -- python3 -c '
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), 5)
    print("OK")
except OSError:
    print("FAIL")' "$2" "$3" 2>/dev/null || echo FAIL
}
# Bounded DNS probes (Package 1): an explicit resolver IP, an explicit
# timeout — never gethostbyname (under a blackout it conflates "no resolver"
# with "blocked"). UDP: a real query, any reply = reachable. TCP: connect.
probe_tcp53() { # pod ip -> OK|FAIL
  "$KUBECTL" exec -n "$NS" "$1" -- python3 -c '
import socket, sys
try:
    socket.create_connection((sys.argv[1], 53), 4)
    print("OK")
except OSError:
    print("FAIL")' "$2" 2>/dev/null || echo FAIL
}
probe_udp53() { # pod ip -> OK|FAIL
  "$KUBECTL" exec -n "$NS" "$1" -- python3 -c '
import socket, sys
q = bytes.fromhex("aabb01000001000000000000076578616d706c6503636f6d0000010001")
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(4)
try:
    s.sendto(q, (sys.argv[1], 53))
    s.recv(512)
    print("OK")
except OSError:
    print("FAIL")' "$2" 2>/dev/null || echo FAIL
}

# --- convergence wait (cc225 lesson: CNI netpol updates converge in 15-60s) ----
# The transition this run performs is the DNS allowance REMOVAL (the old
# policy allowed kube-dns; the new one does not). Wait, bounded, for the
# blackout to take effect on the worker Pod before measuring.
CONVERGED=0
for _ in {1..12}; do
  blocked="$(probe_udp53 netpol-probe-worker "$RESOLVER" 2>/dev/null || echo FAIL)"
  allowed="$(probe_tcp netpol-probe-worker "$MODEL_IP" 8080 2>/dev/null || echo FAIL)"
  if [[ "$blocked" == FAIL && "$allowed" == OK ]]; then CONVERGED=1; break; fi
  sleep 5
done
if (( CONVERGED )); then
  echo "convergence: DNS blackout effective on the worker Pod"
else
  echo "WARN: convergence not observed after 60s — hard checks measure the actual state"
fi

# --- [5/6] probes ----------------------------------------------------------------
# (probe_tcp/probe_tcp53/probe_udp53 are defined above, before the
#  convergence loop — bash requires definition before invocation)
HARD_TOTAL=0; HARD_PASS=0; FAILED=0; INFO_N=0; EXT_SKIPPED=0
check() { # $1=pod $2=kind(tcp|tcp53|udp53) $3=target $4=port $5=expected $6=name
  local got
  HARD_TOTAL=$((HARD_TOTAL + 1))
  case "$2" in
    tcp)   got="$(probe_tcp "$1" "$3" "$4")" ;;
    tcp53) got="$(probe_tcp53 "$1" "$3")" ;;
    udp53) got="$(probe_udp53 "$1" "$3")" ;;
  esac
  if [[ "$got" == "$5" ]]; then
    echo "PASS  $6: $1 $3${4:+:$4} -> $got (expected $5)"
    HARD_PASS=$((HARD_PASS + 1))
  else
    echo "MISMATCH $6: $1 $3${4:+:$4} -> $got (expected $5)"
    FAILED=$((FAILED + 1))
  fi
}
info() { INFO_N=$((INFO_N + 1)); echo "INFO  $*"; }

# Paired SSH (Package 1): the control OK is the MANDATORY precondition —
# only then is the worker FAIL on the same address+port evidence of the
# policy, never of a dead SSH.
check netpol-probe-control tcp "$OPIK_HOST_IP" 22 OK   "control->host-ssh(paired precondition)"
check netpol-probe-worker  tcp "$OPIK_HOST_IP" 22 FAIL "worker->host-ssh(port-narrowing)"
# worker-labeled: allowed paths OK, everything else blocked (DNS blackout)
check netpol-probe-worker tcp "$MODEL_IP" 8080 OK        "worker->model"
check netpol-probe-worker tcp "$OPIK_HOST_IP" 8080 OK    "worker->opik-published"
check netpol-probe-worker tcp 1.1.1.1 80 FAIL            "worker->internet"
check netpol-probe-worker tcp53 "$RESOLVER" "" FAIL      "worker->dns-tcp(resolver)"
check netpol-probe-worker udp53 "$RESOLVER" "" FAIL      "worker->dns-udp(resolver)"
check netpol-probe-worker udp53 1.1.1.1 "" FAIL          "worker->dns-udp(1.1.1.1)"
# control: unlabeled pod — positive control for the probe machinery AND DNS
check netpol-probe-control tcp 1.1.1.1 80 OK             "control->internet(proof-of-work)"
check netpol-probe-control tcp53 "$RESOLVER" "" OK       "control->dns-tcp(resolver,positive)"
check netpol-probe-control udp53 "$RESOLVER" "" OK       "control->dns-udp(resolver,positive)"
# fresh: deny-all in BOTH directions
check netpol-probe-fresh tcp "$MODEL_IP" 8080 FAIL       "fresh->model"
check netpol-probe-fresh tcp 1.1.1.1 80 FAIL             "fresh->internet"
check netpol-probe-fresh udp53 "$RESOLVER" "" FAIL       "fresh->dns-udp(resolver)"
# ingress (Package 1): the listener on :8080 excludes 'nothing listens' —
# a FAIL on the fresh Pod can only be the deny-all Ingress policy
check netpol-probe-control tcp "$WORKER_POD_IP" 8080 OK  "control->worker-pod(ingress allowed)"
check netpol-probe-control tcp "$FRESH_POD_IP" 8080 FAIL "control->fresh-pod(ingress denied)"
# cutover: after the break, ONLY the new versioned policies remain
REMAINING="$("$KUBECTL" get networkpolicy -n "$NS" -o name 2>/dev/null | grep -E '/stanok-' | sort)"
EXPECTED="$(printf 'networkpolicy.networking.k8s.io/%s\nnetworkpolicy.networking.k8s.io/%s\n' "$NEW1" "$NEW2" | sort)"
HARD_TOTAL=$((HARD_TOTAL + 1))
if [[ "$REMAINING" == "$EXPECTED" ]] && (( ! DELETE_FAILED )); then
  echo "PASS  cutover: only $NEW1 $NEW2 remain (old names absent — DNS blackout claim is valid)"
  HARD_PASS=$((HARD_PASS + 1))
else
  echo "MISMATCH cutover: remaining stanok- policies: ${REMAINING:-none} (expected only the new versioned names; delete_failed=$DELETE_FAILED) — old permissions LINGER"
  FAILED=$((FAILED + 1))
fi

# informational only (never counted as a hard check):
# - a DIRECT probe of the post-DNAT address: proven 2026-10-10 it times out
#   even UNLABELED (not routable from pods without the DNAT path) — expected
#   OK there would be a false red, expected FAIL a false green.
info "opik-post-DNAT direct: $(probe_tcp netpol-probe-worker "$OPIK_BACKEND_IP" 8080) on $OPIK_BACKEND_IP:8080 (informational: unreachable from pods by design)"
# - a foreign port on the backend address: a FAIL here is indistinguishable
#   from 'nothing listens'; the hard port-narrowing proof is the paired SSH.
info "opik-net-port-narrowing: $(probe_tcp netpol-probe-worker "$OPIK_BACKEND_IP" 8081) on $OPIK_BACKEND_IP:8081 (informational)"

# external host-exposure: hard only when a LAN peer is provided
if [[ -n "${STANOK_LAN_PEER:-}" ]]; then
  ext() { ssh -o BatchMode=yes -o ConnectTimeout=5 "$STANOK_LAN_PEER" \
            "timeout 5 bash -c '</dev/tcp/$1/$2'" 2>/dev/null && echo OK || echo FAIL; }
  for spec in "$OPIK_HOST_IP 22 host-ssh" "$OPIK_HOST_IP 8080 opik-from-LAN"; do
    set -- $spec
    got="$(ext "$1" "$2")"
    if [[ "$got" == FAIL ]]; then echo "PASS  external-$3: $1:$2 -> FAIL (not exposed)"
    else echo "MISMATCH external-$3: $1:$2 -> $got (expected FAIL: host must not be open to LAN)"; FAILED=$((FAILED + 1)); fi
  done
else
  EXT_SKIPPED=2
  echo "SKIP  external host-exposure x2 (STANOK_LAN_PEER not set — measurement inactive, not passed)"
fi

# --- [6/6] verdict ----------------------------------------------------------------
{
  echo "revision: $REV"
  echo "applied: $NEW1 $NEW2"
  echo "old names captured: ${#OLD_POLICIES[@]} (${OLD_POLICIES[*]:-none})"
} > "$EV/policies.txt"
if (( FAILED )); then
  echo "VERDICT: FAIL ($FAILED mismatch(es)) — $HARD_PASS/$HARD_TOTAL hard checks passed ($EXT_SKIPPED external checks SKIPPED, $INFO_N INFO) — evidence: $EV"
  exit 1
fi
echo "VERDICT: PASS — $HARD_PASS/$HARD_TOTAL hard checks passed ($EXT_SKIPPED external checks SKIPPED, $INFO_N INFO) — evidence: $EV"
exit 0
