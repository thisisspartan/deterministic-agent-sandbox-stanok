# syntax=docker/dockerfile:1
#
# stanok machine image — stack-agnostic worker container.
#
# Design decision (replaces the bash-gate + read-guard + custom `run` MCP tool
# from waves 1-3): the model gets native Bash back. The security boundary
# moves from "approve every command in advance" to "one strong container +
# resource limits + external, unwritable verification". The runtime side of
# that boundary is the k8s worker Job (k8s/worker-job.yaml.tmpl: non-root,
# dropped capabilities, RuntimeDefault seccomp, read-only root, NetworkPolicy)
# rendered and applied by launcher/k8s.py.
#
# R4 (hermetic image, supersedes the old bind-mount decision): the image
# NOW bakes in Node.js and the Claude Code CLI 2.1.88. The old rule was
# "bind-mount the host CLI, don't reinstall" — the owner reversed it: a
# self-contained image where `docker run --rm $IMAGE claude --version`
# IS the version proof, with zero host coupling at container start.
# The CLI is staged into .build-context/claude-code-2.1.88/ by setup.sh
# from $STANOK_CLI_DIR (the operator's validated checkout) — cli.js +
# package.json + the vendored ripgrep binary (vendor/ripgrep/x64-linux/rg,
# required by the CLI's native sandbox at startup), no .git/source/
# other-platforms/maps. Node comes from the
# official nodejs.org tarball, NOT a copy of the host's /usr/bin/node
# (a host ELF is dynamically linked against the host glibc and is not
# portable into bookworm). The SDK below is still installed from sdist
# (--no-binary): the wheel bundles a second CLI (_bundled/claude) that we
# do not want in the image.
#
# What IS baked in: the launcher's own Python runtime (claude-agent-sdk),
# Node.js + the Claude Code CLI, and a minimal, generic toolchain so the
# MODEL can build/test ANY project stack via native Bash — python3/uv
# out of the box. Everything else (Go, Rust, JVM, ...) is one apt-get/curl
# line added here the day a real ticket actually needs it. Do not
# pre-guess every stack the project might ever use.

# W7 supply-chain pin (same pattern as the uv COPY below): the digest is the
# manifest-list digest from `docker buildx imagetools inspect
# debian:bookworm-slim` (2026-10-08) — a tag move on Docker Hub can no
# longer change what we build FROM. Human-readable tag: debian:bookworm-slim
# (bookworm, image created 2026-10-05).
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ARG STANOK_UID=10001
ARG STANOK_GID=10001

# Image provenance: setup.sh computes sha256 over the digest inputs
# (Dockerfile + scripts/run.sh + scripts/stacks/*.toml sorted + image-requirements.lock —
# the same list gates.DIGEST_INPUTS declares) and passes it as
# --build-arg STANOK_DIGEST.
# Doctor re-computes the same digest via the SAME function (gates.py
# preflight_image; CC-106: moved off the launch path — the former blocking
# rc=25 is freed) and fails closed on a mismatch — an image older than the
# Dockerfile/STACKS registry becomes a 1-second doctor failure instead of
# a mid-run ENV-FAIL.
ARG STANOK_DIGEST=
LABEL stanok.digest="${STANOK_DIGEST}"

# --- OS packages -------------------------------------------------------------
# git                     — the Pod's patch mechanism: k8s.pack_tree transports
#                           the tree as `git archive HEAD`, pod_runner.py
#                           re-inits git on the unpacked copy (single "base"
#                           commit) and after the run produces the change
#                           patch with `git diff base..HEAD`. The model also
#                           gets `git log`/`git blame`/`git diff` for context.
# ca-certificates, curl   — HTTPS to the model server (https deployments)
#                           and in-container debugging. Since P1
#                           (SPEC-STANOK-K8S-RUNTIME-2026-10-10) the network
#                           boundary is the rendered NetworkPolicy
#                           (launcher/netpol.py + k8s/networkpolicy.yaml.tmpl):
#                           the worker Pod egress allows ONLY the model server
#                           plus the Opik tracing backend (CC-225); the
#                           fresh-check Pod is deny-all. Packages from
#                           the internet are therefore NOT installable at run
#                           time — the stack lives in the image.
# build-essential         — most "curl | sh" language installers and native
#                           npm/pip packages with C extensions need a compiler.
# python3/venv            — (a) runs the launcher itself, (b) gives
#                           Python-stack tickets a working interpreter with
#                           zero extra setup. Package management is uv
#                           (baked in below), not pip.
# socat                   — the CLI's network bridge (allowedDomains) forwards
#                           the sandbox's HTTP/SOCKS bridge sockets via socat;
#                           the CLI hard-fails at startup without it (verified:
#                           "dependencies are missing: socat not installed").
# jq                      — JSON tooling for the model's native Bash (the
#                           machine's CLAUDE.md gives the model unrestricted
#                           Bash; jq is the standard JSON processor). The
#                           old bash-hook consumer (hooks/verifier.sh) is gone
#                           (R1 in-process hook), but the tool stays: it is
#                           part of the generic toolchain, and the stack
#                           manifest's preflight line is probed INSIDE the
#                           image by doctor's image preflight (preflight_image,
#                           CC-106 — off the launch path) so a silent absence
#                           can never recur.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git \
      ca-certificates \
      curl \
      build-essential \
      socat \
      jq \
      python3 \
      python3-venv \
    && rm -rf /var/lib/apt/lists/*

# --- uv (the image's package manager AND the py stack runner) -----------
# Pinned binary from the official uv image. UV_SYSTEM_PYTHON=1 installs
# into the system python; UV_PYTHON_PREFERENCE=only-system forbids
# downloading a managed python (no GitHub fetches at build or run time);
# UV_NO_CACHE=1 keeps builds and runs hermetic.
# UV_BREAK_SYSTEM_PACKAGES=1: bookworm's system python is PEP 668
# "externally managed" — without this, uv refuses the system install.
# W7 supply-chain pin: the digest is the manifest-list digest from
# `docker buildx imagetools inspect ghcr.io/astral-sh/uv:0.5.24`
# (2026-09-21) — a tag move on ghcr can no longer change what we COPY.
COPY --from=ghcr.io/astral-sh/uv:0.5.24@sha256:2381d6aa60c326b71fd40023f921a0a3b8f91b14d5db6b90402e65a635053709 /uv /usr/local/bin/uv
ENV UV_SYSTEM_PYTHON=1 \
    UV_PYTHON_PREFERENCE=only-system \
    UV_NO_CACHE=1 \
    UV_BREAK_SYSTEM_PACKAGES=1

# --- Launcher runtime ---------------------------------------------------
# The image's package set is pinned by image-requirements.lock — the single
# source: the two direct pins (claude-agent-sdk, pytest) plus their full
# transitive closure (mcp/anyio/sniffio/...), every package with sha256
# hashes, resolved for python 3.11/linux (the image's system python).
# Requirements format (pip-style), NOT uv's TOML project lock — the name says
# what it is. Bump a dependency by regenerating the lock deliberately:
#   printf 'claude-agent-sdk==X\npytest==Y\n' | \
#     uv pip compile - -o image-requirements.lock --python-version 3.11 \
#       --python-platform linux --generate-hashes
# image-requirements.lock is a digest input (setup.sh + gates.DIGEST_INPUTS):
# a lock change moves the image digest, so doctor fails a stale image instead
# of silently shipping a different package set.
# --no-binary claude-agent-sdk: install from sdist, NOT the wheel — the
# wheel ships _bundled/claude (a second CLI, ~300 MB). The sdist build has
# no _bundled dir; the SDK's cli_path (launcher/session.py passes
# cfg.claude_bin; config.py resolves it from STANOK_CLAUDE_BIN / PATH) names
# `claude` — inside the container that is the baked-in /usr/local/bin/claude.
# pytest — the py stack's test-runner in scripts/run.sh is
# `env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider -o pythonpath=src`;
# Python-stack tickets run their suites with it. An unpinned install drifts
# on every rebuild, and a missing pytest in the image is exactly the
# ENV-FAIL class that run.sh's rc=6 and doctor's image preflight
# (preflight_image, CC-106 — off the launch path) exist to catch.
COPY image-requirements.lock /opt/image-requirements.lock
RUN uv pip install --no-binary claude-agent-sdk -r /opt/image-requirements.lock

# --- Node.js + Claude Code CLI (R4: hermetic image) ------------------------
# Node: official nodejs.org tarball, extracted over /usr/local (bin/node,
# bin/npm, lib/node_modules/npm). NOT a COPY of the host's /usr/bin/node —
# that ELF is dynamically linked against the host glibc and is not
# portable into bookworm.
# CLI: staged by setup.sh into .build-context/claude-code-2.1.88/ (cli.js +
# package.json + vendor/ripgrep/x64-linux/rg from $STANOK_CLI_DIR).
# Bump both deliberately.
ARG NODE_VERSION=22.22.3
# W7 supply-chain pin: sha256 of node-v22.22.3-linux-x64.tar.gz from the
# official https://nodejs.org/dist/v22.22.3/SHASUMS256.txt (2026-09-21).
# Download to a temp file, verify, THEN extract — a mismatched tarball
# fails the build instead of being silently unpacked over /usr/local.
ARG NODE_SHA256=c7a10d6816da8eaaa7534dd73c71c6e2b2c391dbbf845e364902d156615dd1b8
RUN set -eux; \
    curl -fsSL -o /tmp/node.tar.gz \
      "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.gz"; \
    echo "${NODE_SHA256}  /tmp/node.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/node.tar.gz --strip-components=1 -C /usr/local; \
    rm -f /tmp/node.tar.gz
COPY .build-context/claude-code-2.1.88/ /opt/claude-code-2.1.88/
# 2026-10-21 external review N2: the staged CLI was COPY'd without an
# in-build verification — the SHA gate lived only in setup.sh, so a stale
# .build-context from an earlier run could survive a build whose digest
# inputs happen to match. In-build parity with the W7 pattern already used
# for uv and node above: setup.sh passes the same hashes it verified as
# --build-arg; empty defaults make `test -n` fail the build, so a build
# that skips the args REFUSES instead of shipping unverified content.
ARG CLI_JS_SHA=
ARG PKG_JSON_SHA=
ARG RG_SHA=
RUN set -eux; \
    test -n "${CLI_JS_SHA}"; test -n "${PKG_JSON_SHA}"; test -n "${RG_SHA}"; \
    { \
      echo "${CLI_JS_SHA}  /opt/claude-code-2.1.88/cli.js"; \
      echo "${PKG_JSON_SHA}  /opt/claude-code-2.1.88/package.json"; \
      echo "${RG_SHA}  /opt/claude-code-2.1.88/vendor/ripgrep/x64-linux/rg"; \
    } | sha256sum -c -
RUN chmod +x /opt/claude-code-2.1.88/cli.js \
    && ln -s /opt/claude-code-2.1.88/cli.js /usr/local/bin/claude

# --- Non-root user -------------------------------------------------------
# Mirrors gates.py's own root_refusal() host-side check: the container must
# not run the model as root either, or a container escape and a host-level
# root compromise become the same bug instead of two separate ones.
# The worker Job pins this exact UID (k8s/worker-job.yaml.tmpl
# securityContext: runAsNonRoot, runAsUser/runAsGroup 10001); the Pod writes
# only to emptyDir volumes and its changes reach the host as a text patch —
# no host file ever carries a Pod-side owner.
RUN groupadd -g "$STANOK_GID" stanok \
    && useradd -m -u "$STANOK_UID" -g "$STANOK_GID" -s /bin/bash stanok

WORKDIR /work
USER stanok

# No ENTRYPOINT/CMD on purpose. The worker Job always passes the full command
# explicitly (/usr/bin/python3 /stanok/runner/pod_runner.py —
# k8s/worker-job.yaml.tmpl). An implicit default here
# would be a second, easy-to-forget place the launch command could drift
# from what launch.sh actually invokes — the same class of bug as the
# README/CLAUDE.md drift found earlier in this project.
