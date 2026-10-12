#!/bin/sh
# One-time root step (operator, 2026-10-12): teach BOTH container runtimes
# that the node-local registry is plain HTTP:
#   - k3s containerd (pull side): /etc/rancher/k3s/registries.yaml — kubelet
#     then pulls the digest-pinned image by itself (after any image GC);
#   - docker (push side, setup.sh): insecure-registries in
#     /etc/docker/daemon.json — without it `docker push` to a non-localhost
#     registry dies with "server gave HTTP response to HTTPS client".
# After this, the manual
# `docker save stanok-machine:latest | sudo k3s ctr -n k8s.io images import -`
# is retired. Idempotent: re-running rewrites the files and restarts docker + k3s.
#
# Run once:  sudo ./k8s/setup-registry.sh   (or with sudo as documented)
set -eu
REGISTRY="${STANOK_REGISTRY:-192.168.122.156:5000}"

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo): this writes /etc/rancher/k3s/registries.yaml and /etc/docker/daemon.json, restarts docker and k3s" >&2
    exit 1
fi

cat > /etc/rancher/k3s/registries.yaml <<EOF
# stanok image delivery (k8s/setup-registry.sh) — plain-HTTP node-local registry
mirrors:
  ${REGISTRY}:
    endpoint:
      - "http://${REGISTRY}"
EOF

# docker: merge insecure-registries into the EXISTING daemon.json — existing
# keys (log-opts, runtimes) are preserved, the registry entry is appended once.
python3 - "$REGISTRY" <<'PY'
import json, sys
path = "/etc/docker/daemon.json"
try:
    with open(path) as f:
        cfg = json.load(f)
except FileNotFoundError:
    cfg = {}
ins = cfg.setdefault("insecure-registries", [])
if sys.argv[1] not in ins:
    ins.append(sys.argv[1])
with open(path, "w") as f:
    json.dump(cfg, f, indent=4)
    f.write("\n")
PY

systemctl restart docker
systemctl restart k3s
echo "registries.yaml + daemon.json(insecure-registries) installed for ${REGISTRY}; docker and k3s restarted."
