#!/usr/bin/env bash
# netpol-smoke.sh — repeatable NEGATIVE network smoke for the K8s runtime
# (SPEC-STANOK-K8S-RUNTIME; closes the cc224 gap: that acceptance check was
# one-shot, this one is re-runnable after every NetworkPolicy change).
#
# Traps this script is built around (operator review 2026-10-10):
#  1. LABEL. stanok-worker-egress selects Pods by label `stanok: worker`
#     (k8s/networkpolicy.yaml). An unlabeled test Pod is NOT restricted and
#     its probes pass — a green result that proves nothing. The probe Pod
#     carries the exact label the worker Job carries.
#  2. CONTROL. The same probe from an UNLABELED pod must reach 1.1.1.1 —
#     otherwise a FAIL could mean "the probe is broken", not "blocked".
#  3. REAL ADDRESSES. The worker's actual paths: model 192.168.8.131:8080,
#     Opik 192.168.122.156:8080 (the policy sees the POST-DNAT destination
#     172.25.0.4 — CC-225; the published-address probe proves the DNATed
#     packet passed the 172.25.0.0/16 rule; a DIRECT probe of 172.25.0.4 is
#     informational only: it times out even UNLABELED, not routable from
#     pods). The port-narrowing proof is 192.168.122.156:22 — the host SSH
#     listens there, so a FAIL on that address+port can only be the policy.
#  4. HOST EXPOSURE. NetworkPolicy guards Pods only. The external check
#     (host SSH/Opik from another LAN machine) runs ONLY when STANOK_LAN_PEER
#     is set; without a peer it is reported SKIP, never silently dropped.
#
# The script RE-APPLIES the policy (delete + apply: the k3s netpol controller
# ignores NetworkPolicy UPDATES) and records the applied manifest's sha256
# together with the results in evidence/netpol-<ts>/.
#
# Usage (on the k3s host):
#   KUBECONFIG=<kubeconfig> [STANOK_LAN_PEER=<ssh-host>] infra/netpol-smoke.sh
# Knobs: STANOK_KUBECTL (default kubectl), STANOK_NAMESPACE (default),
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
MANIFEST="$ROOT/k8s/networkpolicy.yaml"
PODS=(netpol-probe-worker netpol-probe-control netpol-probe-fresh)

mkdir -p "$EV"
exec > >(tee "$LOG") 2>&1

die() { echo "FATAL: $*"; exit 2; }

# --- [1/5] preflight -------------------------------------------------------------
command -v "$KUBECTL" >/dev/null || die "kubectl not found"
"$KUBECTL" get nodes >/dev/null 2>&1 || die "cluster unreachable (kubectl get nodes)"
[[ -f "$MANIFEST" ]] || die "manifest missing: $MANIFEST"

echo "== netpol-smoke $TS =="
echo "manifest sha256: $(sha256sum "$MANIFEST" | cut -d' ' -f1)"
sha256sum "$MANIFEST" > "$EV/manifest.sha256"

# --- [2/5] re-apply the policy (k3s ignores netpol UPDATES) --------------------
"$KUBECTL" delete -n "$NS" -f "$MANIFEST" --ignore-not-found >/dev/null || die "netpol delete failed"
"$KUBECTL" apply -n "$NS" -f "$MANIFEST" >/dev/null || die "netpol apply failed"
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
check netpol-probe-worker tcp 192.168.8.131 8080 OK  "worker->model"
check netpol-probe-worker tcp 192.168.122.156 8080 OK "worker->opik-published"
# The 172.25.0.0/16:8080 rule is proven by the check above: the DNATed packet
# (FORWARD sees 172.25.0.4, CC-225) passed. A DIRECT probe of the post-DNAT
# address is NOT a valid test: proven 2026-10-10 it times out even from an
# UNLABELED pod (the address is not routable from pods without the DNAT path)
# — expected-OK there would be a false red, expected-FAIL a false green.
echo "INFO  opik-post-DNAT direct: $(probe_tcp netpol-probe-worker 172.25.0.4 8080) on 172.25.0.4:8080 (informational: unreachable from pods by design, see comment)"
check netpol-probe-worker dns example.com "" OK        "worker->dns"
check netpol-probe-worker tcp 1.1.1.1 80 FAIL          "worker->internet"
check netpol-probe-worker tcp 192.168.122.156 22 FAIL  "worker->host-ssh(port-narrowing)"
# control: unlabeled pod proves the probe machinery and cluster egress work
check netpol-probe-control tcp 1.1.1.1 80 OK           "control->internet(proof-of-work)"
# fresh: deny-all
check netpol-probe-fresh tcp 192.168.8.131 8080 FAIL  "fresh->model"
check netpol-probe-fresh dns example.com "" FAIL       "fresh->dns"
check netpol-probe-fresh tcp 1.1.1.1 80 FAIL           "fresh->internet"

# informational: a foreign port on the Opik net. NOT a hard check: a FAIL
# here is indistinguishable from "nothing listens on that port"; the hard
# port-narrowing proof is worker->host-ssh above (host SSH definitely listens).
echo "INFO  opik-net-port-narrowing: $(probe_tcp netpol-probe-worker 172.25.0.4 8081) on 172.25.0.4:8081 (informational)"

# external host-exposure: hard only when a LAN peer is provided
if [[ -n "${STANOK_LAN_PEER:-}" ]]; then
  ext() { ssh -o BatchMode=yes -o ConnectTimeout=5 "$STANOK_LAN_PEER" \
            "timeout 5 bash -c '</dev/tcp/$1/$2'" 2>/dev/null && echo OK || echo FAIL; }
  for spec in "192.168.122.156 22 host-ssh" "192.168.122.156 8080 opik-from-LAN"; do
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
