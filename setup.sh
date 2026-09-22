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
CLI_JS_SHA="a5f461302c9a10185f2ccb6100daf6836577d3e72b5df61732fba985bdc07994"
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
mkdir -p "$DIR/.build-context/claude-code-2.1.88/vendor/ripgrep/x64-linux"
cp -f "$CLI_SRC/cli.js" "$CLI_SRC/package.json" "$DIR/.build-context/claude-code-2.1.88/"
cp -f "$CLI_SRC/vendor/ripgrep/x64-linux/rg" "$DIR/.build-context/claude-code-2.1.88/vendor/ripgrep/x64-linux/"

echo "--- building the machine image (Docker boundary) ---"
# The .venv above is only the HOST-side python for the Runner's host-side
# gates; the run itself executes in the image (launcher/sandbox.py runs the
# image system python, which carries the SDK).
# Image provenance: bake sha256(Dockerfile + scripts/run.sh) into the image
# LABEL stanok.digest. Doctor re-computes this digest
# (launcher/tests_harness/test_doctor.py::test_docker_image_digest_matches)
# and fails if the image no longer matches the tree (CC-106: the check moved
# out of the launch path).
STANOK_DIGEST="$(cat "$DIR/Dockerfile" "$DIR/scripts/run.sh" | sha256sum | cut -d' ' -f1)"
docker build -t "${STANOK_DOCKER_IMAGE:-stanok-machine:latest}" -f "$DIR/Dockerfile" "$DIR" \
    --build-arg STANOK_DIGEST="$STANOK_DIGEST"

echo
echo "Environment ready. Machine check:"
echo "  bash hooks/doctor.sh"
