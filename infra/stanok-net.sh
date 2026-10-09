#!/usr/bin/env bash
# stanok-net — S4 (SPEC-NETWORK-2026-10-09): the worker's dedicated bridge
# network + the iptables policy the launcher's network_preflight verifies.
#
# Policy (E2): the worker container reaches ONLY the model server; external
# internet and host services are closed. Enforcement points:
#   DOCKER-USER -> STANOK-NET  (FORWARD: container -> external, MASQUERADE'd)
#   INPUT       -> STANOK-NET  (container -> host services)
# Docker's own POSTROUTING masquerade for the subnet is added automatically
# when the network is created — no NAT rules here.
#
# Idempotent: safe to run repeatedly (removes old jumps, recreates the chain).
# Install: systemd unit stanok-net.service (After=docker.service). The
# supervisor prepares this file; the OPERATOR installs and runs it as root.
set -euo pipefail

NET="${STANOK_DOCKER_NETWORK:-stanok-net}"
SUBNET="${STANOK_NET_SUBNET:-172.28.0.0/16}"
MODEL_HOST="${STANOK_MODEL_HOST:-192.168.8.131}"
MODEL_PORT="${STANOK_MODEL_PORT:-8080}"

# 1. the network (create only if absent; a pre-existing network keeps its subnet)
if ! docker network inspect "$NET" >/dev/null 2>&1; then
    docker network create --subnet "$SUBNET" "$NET"
    echo "created network $NET ($SUBNET)"
fi

# 2. remove our jumps first (idempotency: never stack duplicates)
remove_jump() {
    local chain="$1"
    while iptables -t filter -D "$chain" -s "$SUBNET" -j STANOK-NET 2>/dev/null; do :; done
}
remove_jump DOCKER-USER
remove_jump INPUT

# 3. (re)create the chain
if iptables -t filter -L STANOK-NET >/dev/null 2>&1; then
    iptables -t filter -F STANOK-NET
else
    iptables -t filter -N STANOK-NET
fi

# 4. the policy: return traffic of allowed flows, the model server, drop rest
iptables -t filter -A STANOK-NET -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -t filter -A STANOK-NET -d "$MODEL_HOST" -p tcp --dport "$MODEL_PORT" -j ACCEPT
iptables -t filter -A STANOK-NET -j DROP

# 5. install the jumps at position 1 (before docker's own rules)
iptables -t filter -I DOCKER-USER 1 -s "$SUBNET" -j STANOK-NET
iptables -t filter -I INPUT 1 -s "$SUBNET" -j STANOK-NET

echo "stanok-net policy installed: $SUBNET -> STANOK-NET (model $MODEL_HOST:$MODEL_PORT only)"
