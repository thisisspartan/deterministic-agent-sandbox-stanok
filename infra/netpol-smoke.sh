#!/usr/bin/env bash
# netpol-smoke.sh — repeatable NEGATIVE network smoke for the K8s runtime
# (SPEC-STANOK-K8S-RUNTIME; closes the cc224 gap: that acceptance check was
# one-shot, this one is re-runnable after every NetworkPolicy change).
#
# Traps this script is built around (operator review 2026-10-10):
#  1. LABEL. stanok-worker-egress selects Pods by label `stanok: worker`
#     (k8s/networkpolicy.yaml.tmpl, rendered by launcher/netpol.py). An
#     unlabeled test Pod is NOT restricted and its probes pass — a green
#     result that proves nothing. The probe Pod carries the exact label the
#     worker Job carries.
#  2. CONTROL. The same probe from an UNLABELED pod must reach 1.1.1.1 —
#     otherwise a FAIL could mean "the probe is broken", not "blocked".
#  3. REAL ADDRESSES (2.4). The manifest template carries NO addresses; this
#     script renders it (STANOK_SERVER_URL is REQUIRED — MODEL_IP is derived
#     from it) and derives the probe targets from the RENDERED manifest: the
#     three /32 cidrs in order = model, Opik published host, Opik post-DNAT
#     container address (CC-225: the policy sees the POST-DNAT destination;
#     the published-address probe proves the DNATed packet passed the
#     post-DNAT /32 rule; a DIRECT probe of the post-DNAT address is
#     informational only: it times out even UNLABELED, not routable from
#     pods). The port-narrowing proof is <opik-host>:22 — the host SSH
#     listens there, so a FAIL on that address+port can only be the policy.
#  4. HOST EXPOSURE. NetworkPolicy guards Pods only. The external check
#     (host SSH/Opik from another LAN machine) runs ONLY when STANOK_LAN_PEER
#     is set; without a peer it is reported SKIP, never silently dropped.
#
# The script RENDERS the manifest (launcher/netpol.py — the applied manifest
# is saved to the evidence dir), RE-APPLIES the policy (delete + apply: the
# k3s netpol controller ignores NetworkPolicy UPDATES) and records the
# applied manifest's sha256 together with the results in evidence/netpol-<ts>/.
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
#       2 = preflight failed (cluster/image unreachable).
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

# --- [1/5] preflight -------------------------------------------------------------
command -v "$KUBECTL" >/dev/null || die "kubectl not found"
"$KUBECTL" get nodes >/dev/null 2>&1 || die "cluster unreachable (kubectl get nodes)"
[[ -f "$TEMPLATE" ]] || die "template missing: $TEMPLATE"
[[ -x "$PY" ]] || die "renderer python missing: $PY"
[[ -n "${STANOK_SERVER_URL:-}" ]] || die "STANOK_SERVER_URL must be set (MODEL_IP is derived from it)"

echo "== netpol-smoke $TS =="
echo "template sha256: $(sha256sum "$TEMPLATE" | cut -d' ' -f1)"

# --- [2/5] render + re-apply the policy (k3s ignores netpol UPDATES) ----------
(cd "$ROOT" && "$PY" -m launcher.netpol) > "$APPLIED" || die "netpol render failed (launcher.netpol)"
echo "rendered: $APPLIED"
echo "applied manifest sha256: $(sha256sum "$APPLIED" | cut -d' ' -f1)"
sha256sum "$APPLIED" > "$EV/manifest.sha256"
# Probe targets = the rendered manifest's three /32 cidrs, in template order
mapfile -t CIDRS < <(grep -oE 'cidr: [0-9.]+/32' "$APPLIED" | awk '{print $2}')
MODEL_IP="${CIDRS[0]%%/*}"; OPIK_HOST_IP="${CIDRS[1]%%/*}"; OPIK_BACKEND_IP="${CIDRS[2]%%/*}"
[[ -n "$MODEL_IP" && -n "$OPIK_HOST_IP" && -n "$OPIK_BACKEND_IP" ]] \
  || die "rendered manifest has fewer than 3 /32 cidrs"
echo "targets: model=$MODEL_IP opik-host=$OPIK_HOST_IP opik-post-dnat=$OPIK_BACKEND_IP"
"$KUBECTL" delete -n "$NS" -f "$APPLIED" --ignore-not-found >/dev/null || die "netpol delete failed"
"$KUBECTL" apply -n "$NS" -f "$APPLIED" >/dev/null || die "netpol apply failed"
echo "policy re-applied (delete+apply)"

cleanup() { "$KUBECTL" delete -n "$NS" --wait=false pod "${PODS[@]}" >/dev/null 2>&1; }
trap cleanup EXIT

# --- [3/5] probe pods: worker-labeled, control (no label), fresh-labeled -------
apply_pod() { # $1=name $2=stanok-label ("" = unlabeled control)
  {
    echo "apiVersion: v1"
    echo "kind: Pod"
    echo "metadata:"
    echo "  name: $1"
    echo "  namespace: $NS"
    if [[ -n "$2" ]]; then
      echo "  labels:"
      echo "    stanok: $2"
    fi
    echo "spec:"
    echo "  restartPolicy: Never"
    echo "  containers:"
    echo "    - name: probe"
    echo "      image: $IMAGE"
    echo "      imagePullPolicy: IfNotPresent"
    echo "      command: [\"sleep\", \"600\"]"
  } | "$KUBECTL" apply -n "$NS" -f - >/dev/null || die "pod $1 create failed"
  "$KUBECTL" wait --for=condition=Ready "pod/$1" -n "$NS" --timeout=120s >/dev/null \
    || die "pod $1 not Ready"
}
apply_pod netpol-probe-worker worker
apply_pod netpol-probe-control ""
apply_pod netpol-probe-fresh fresh
echo "probe pods Ready"

# --- [4/5] probes ----------------------------------------------------------------
probe_tcp() { # pod host port -> OK|FAIL
  "$KUBECTL" exec -n "$NS" "$1" -- python3 -c '
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), 5)
    print("OK")
except OSError:
    print("FAIL")' "$2" "$3" 2>/dev/null || echo FAIL
}
probe_dns() { # pod hostname -> OK|FAIL
  "$KUBECTL" exec -n "$NS" "$1" -- python3 -c '
import socket, sys
try:
    socket.gethostbyname(sys.argv[1])
    print("OK")
except OSError:
    print("FAIL")' "$2" 2>/dev/null || echo FAIL
}

FAILED=0
check() { # $1=pod $2=kind(tcp|dns) $3=target $4=port $5=expected $6=name
  local got
  if [[ "$2" == tcp ]]; then got="$(probe_tcp "$1" "$3" "$4")"
  else got="$(probe_dns "$1" "$3")"; fi
  if [[ "$got" == "$5" ]]; then
    echo "PASS  $6: $1 $3${4:+:$4} -> $got (expected $5)"
  else
    echo "MISMATCH $6: $1 $3${4:+:$4} -> $got (expected $5)"
    FAILED=$((FAILED + 1))
  fi
}

# worker-labeled: allowed paths OK, everything else blocked
check netpol-probe-worker tcp "$MODEL_IP" 8080 OK        "worker->model"
check netpol-probe-worker tcp "$OPIK_HOST_IP" 8080 OK    "worker->opik-published"
# The post-DNAT /32 rule is proven by the check above: the DNATed packet
# (FORWARD sees $OPIK_BACKEND_IP, CC-225) passed. A DIRECT probe of the
# post-DNAT address is NOT a valid test: proven 2026-10-10 it times out even
# from an UNLABELED pod (the address is not routable from pods without the
# DNAT path) — expected-OK there would be a false red, expected-FAIL a false
# green.
echo "INFO  opik-post-DNAT direct: $(probe_tcp netpol-probe-worker "$OPIK_BACKEND_IP" 8080) on $OPIK_BACKEND_IP:8080 (informational: unreachable from pods by design, see comment)"
check netpol-probe-worker dns example.com "" OK          "worker->dns"
check netpol-probe-worker tcp 1.1.1.1 80 FAIL            "worker->internet"
check netpol-probe-worker tcp "$OPIK_HOST_IP" 22 FAIL    "worker->host-ssh(port-narrowing)"
# control: unlabeled pod proves the probe machinery and cluster egress work
check netpol-probe-control tcp 1.1.1.1 80 OK             "control->internet(proof-of-work)"
# fresh: deny-all
check netpol-probe-fresh tcp "$MODEL_IP" 8080 FAIL       "fresh->model"
check netpol-probe-fresh dns example.com "" FAIL         "fresh->dns"
check netpol-probe-fresh tcp 1.1.1.1 80 FAIL             "fresh->internet"

# informational: a foreign port on the Opik backend address. NOT a hard check:
# a FAIL here is indistinguishable from "nothing listens on that port"; the
# hard port-narrowing proof is worker->host-ssh above (host SSH definitely
# listens).
echo "INFO  opik-net-port-narrowing: $(probe_tcp netpol-probe-worker "$OPIK_BACKEND_IP" 8081) on $OPIK_BACKEND_IP:8081 (informational)"

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
  echo "SKIP  external host-exposure (STANOK_LAN_PEER not set — measurement inactive, not passed)"
fi

# --- [5/5] verdict ----------------------------------------------------------------
if (( FAILED )); then
  echo "VERDICT: FAIL ($FAILED mismatch(es)) — evidence: $EV"
  exit 1
fi
echo "VERDICT: PASS — evidence: $EV"
exit 0
