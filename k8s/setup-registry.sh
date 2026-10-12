#!/bin/sh
# One-time root step (operator, 2026-10-12): teach k3s containerd that the
# node-local registry is plain HTTP. After this, kubelet pulls the digest-pinned
# image by itself (after any image GC) — the manual
# `docker save stanok-machine:latest | sudo k3s ctr -n k8s.io images import -`
# is retired. Idempotent: re-running rewrites the file and restarts k3s.
#
# Run once:  sudo ./k8s/setup-registry.sh   (or with sudo as documented)
set -eu
REGISTRY="${STANOK_REGISTRY:-192.168.122.156:5000}"

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo): this writes /etc/rancher/k3s/registries.yaml and restarts k3s" >&2
    exit 1
fi

cat > /etc/rancher/k3s/registries.yaml <<EOF
# stanok image delivery (k8s/setup-registry.sh) — plain-HTTP node-local registry
mirrors:
  ${REGISTRY}:
    endpoint:
      - "http://${REGISTRY}"
EOF

systemctl restart k3s
echo "registries.yaml installed for ${REGISTRY}; k3s restarted."
