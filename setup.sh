#!/usr/bin/env bash
# Machine environment setup: .venv (host-side gate python) + launcher
# dependencies + the Docker machine image.
# Run: ./setup.sh  (from the root of the stanok repo)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not found on PATH. Install it with:" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
    echo "--- creating .venv (uv) ---"
    uv venv "$DIR/.venv"
fi

echo "--- installing dependencies (uv) ---"
uv pip install --no-binary claude-agent-sdk -r "$DIR/requirements.txt"

echo "--- SDK check ---"
.venv/bin/python -c "from claude_agent_sdk import query; print('claude-agent-sdk OK')"

echo "--- staging the Claude Code CLI into the build context (R4) ---"
# The Dockerfile COPYs .build-context/claude-code-2.1.88/ — the CLI checkout
# lives OUTSIDE the build context ($DIR), so stage only the essential files
# here first: cli.js + package.json, plus the vendored ripgrep binary for
# x64-linux (the CLI's native sandbox hard-fails at startup without
# vendor/ripgrep/x64-linux/rg). No .git/source/other-platforms/maps.
# W13: no default path — the validated claude-code 2.1.88 checkout is
# operator-specific (npm 2.1.88 is a 404; the checkout is the only source).
# A missing STANOK_CLI_DIR fails closed (exit 1) instead of silently
# falling back to a host path that may not exist on another machine.
# The SHA-256 check below stays hard: a missing or tampered checkout
# fails the build (exit 1) — it never silently ships.
CLI_SRC="${STANOK_CLI_DIR:?ERROR: STANOK_CLI_DIR is not set — point it at the validated claude-code 2.1.88 checkout (cli.js + package.json + vendor/ripgrep/x64-linux/rg)}"
# Pinned hashes of the validated claude-code 2.1.88 staging sources —
# a tampered or wrong checkout must fail the build, not silently ship.
CLI_JS_SHA="e170506c2551a25bf7735a2b8e7df4433256ff0ce7fa5cffc0ceb2a84261367b"
PKG_JSON_SHA="e21f9e98fa4ea8b4d007063d92c631df1bbed6d11c9e79c5fcdeb9f4859dc8fa"
RG_SHA="55c2b8dd910f390b06b3a7c620603489b83fdfb647665e4d4bb32f3f54f09ea1"
if [[ ! -f "$CLI_SRC/cli.js" || ! -f "$CLI_SRC/package.json" || ! -f "$CLI_SRC/vendor/ripgrep/x64-linux/rg" ]]; then
    echo "ERROR: CLI staging source not found: $CLI_SRC (need cli.js + package.json + vendor/ripgrep/x64-linux/rg)" >&2
    echo "  Set STANOK_CLI_DIR to the validated claude-code 2.1.88 checkout." >&2
    exit 1
fi
actual_cli="$(sha256sum "$CLI_SRC/cli.js" | cut -d' ' -f1)"
actual_pkg="$(sha256sum "$CLI_SRC/package.json" | cut -d' ' -f1)"
actual_rg="$(sha256sum "$CLI_SRC/vendor/ripgrep/x64-linux/rg" | cut -d' ' -f1)"
if [[ "$actual_cli" != "$CLI_JS_SHA" || "$actual_pkg" != "$PKG_JSON_SHA" || "$actual_rg" != "$RG_SHA" ]]; then
    echo "ERROR: CLI staging source hash mismatch (tampered or wrong checkout):" >&2
    echo "  cli.js:       got $actual_cli want $CLI_JS_SHA" >&2
    echo "  package.json: got $actual_pkg want $PKG_JSON_SHA" >&2
    echo "  rg:           got $actual_rg want $RG_SHA" >&2
    exit 1
fi
# CC-143: anchor gate — the SHA match proves the file is byte-identical to
# the pinned bundle, but a rebuilt-from-different-source bundle could
# coincidentally match the SHA without carrying the 11 patch anchors.
# verify.sh confirms the anchors are present (fail-fast).
# STATUS (2026-10-21 external review N3): this check is ADVISORY, by
# design — the hard gate is the SHA block above (exit 1 on any mismatch).
# The bundle's STOCK base branch legitimately has no patches/verify.sh, so
# its absence is a WARN-skip, not a failure: an anchor-check absence is
# never a build error; an anchor-check FAILURE (verify.sh present and
# failing) aborts the build because its non-zero rc propagates here.
if [[ -f "$CLI_SRC/patches/verify.sh" ]]; then
    echo "--- CLI patch anchor check (CC-143) ---"
    bash "$CLI_SRC/patches/verify.sh" "$CLI_SRC/cli.js"
else
    echo "WARN: $CLI_SRC/patches/verify.sh not found — skipping anchor check" >&2
fi
mkdir -p "$DIR/.build-context/claude-code-2.1.88/vendor/ripgrep/x64-linux"
cp -f "$CLI_SRC/cli.js" "$CLI_SRC/package.json" "$DIR/.build-context/claude-code-2.1.88/"
cp -f "$CLI_SRC/vendor/ripgrep/x64-linux/rg" "$DIR/.build-context/claude-code-2.1.88/vendor/ripgrep/x64-linux/"

echo "--- building the machine image (Docker boundary) ---"
# The .venv above is only the HOST-side python for the Runner's host-side
# gates; the run itself executes in the Pod (launcher/pod_runner.py drives
# the image system python, which carries the SDK).
# Image provenance: bake sha256 over the digest inputs (Dockerfile +
# scripts/run.sh + scripts/stacks/*.toml — the STACKS registry +
# image-requirements.lock — the image dependency lock) into the image LABEL
# stanok.digest. The inputs
# are concatenated in EXPLICIT filename order (LC_ALL=C ls | LC_ALL=C sort —
# no reliance on shell-glob order and no locale dependence: the 2026-10-21
# external review N1 found that a plain `sort` follows the ambient locale's
# collation while gates.DIGEST_INPUTS/gates.py sorts bytewise; the C locale
# makes both byte-identical), the same list and order gates.DIGEST_INPUTS
# declares in doctor: test_image_digest_inputs.py pins the two lists equal
# AND pins the byte-identity of the two computations,
# test_docker_image_digest_matches fails a stale image (CC-106: the check
# lives in doctor, not the launch path).
# shellcheck disable=SC2046,SC2012  # word splitting here is the point (the
# expansion is the file list for cat; the glob is restricted to the known
# ASCII registry filenames, so `ls` is deliberate — find would only break the
# test_image_digest_inputs parser that pins this exact form)
STANOK_DIGEST="$(cat "$DIR/Dockerfile" "$DIR/scripts/run.sh" $(LC_ALL=C ls "$DIR"/scripts/stacks/*.toml | LC_ALL=C sort) "$DIR/image-requirements.lock" | sha256sum | cut -d' ' -f1)"
IMAGE_NAME="${STANOK_DOCKER_IMAGE:-stanok-machine:latest}"
# N2 (2026-10-21 review): the CLI hashes verified above are passed into the
# build so the Dockerfile re-verifies the staged files in-build (a stale
# .build-context then fails the build instead of shipping).
docker build -t "$IMAGE_NAME" -f "$DIR/Dockerfile" "$DIR" \
    --build-arg STANOK_DIGEST="$STANOK_DIGEST" \
    --build-arg CLI_JS_SHA="$CLI_JS_SHA" \
    --build-arg PKG_JSON_SHA="$PKG_JSON_SHA" \
    --build-arg RG_SHA="$RG_SHA"

# Image delivery (operator 2026-10-12): push to the node-local registry so k3s
# pulls BY DIGEST (launcher/k8s.py resolves the RepoDigest at launch). This
# retires the manual `docker save | sudo k3s ctr import` and survives kubelet
# image GC. The registry container is ensured here (docker group, no sudo);
# the one-time root step (k3s registries.yaml + docker insecure-registries —
# plain HTTP on both sides) is k8s/setup-registry.sh (root, operator).
REGISTRY="${STANOK_REGISTRY:-192.168.122.156:5000}"
if ! docker inspect stanok-registry >/dev/null 2>&1; then
    docker run -d --name stanok-registry --restart unless-stopped \
        -p "${REGISTRY}:5000" -v stanok-registry-data:/var/lib/registry \
        registry:2
fi
docker tag "$IMAGE_NAME" "${REGISTRY}/${IMAGE_NAME}"
docker push "${REGISTRY}/${IMAGE_NAME}"
docker inspect --format='{{json .RepoDigests}}' "$IMAGE_NAME" \
    | grep -o "\"${REGISTRY}[^\"]*\"" >/dev/null \
    || { echo "FATAL: image not pushed to ${REGISTRY} — RepoDigest unresolved" >&2; exit 1; }
echo "Image pushed: ${REGISTRY}/${IMAGE_NAME} (k8s resolves the digest at launch)"

echo
echo "Environment ready. Machine check:"
echo "  bash hooks/doctor.sh"
