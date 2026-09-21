# syntax=docker/dockerfile:1
#
# stanok machine image — stack-agnostic worker container.
#
# Design decision (replaces bwrap + bash-gate + read-guard + custom `run` MCP
# tool from waves 1-3): the model gets native Bash back. The security boundary
# moves from "approve every command in advance" to "one strong container +
# resource limits + external, unwritable verification" — see launcher/sandbox.py
# for the runtime side of that boundary.
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

FROM debian:bookworm-slim

ARG STANOK_UID=10001
ARG STANOK_GID=10001
# Pin deliberately. The SDK wheel bundles a second, independently-versioned
# Claude Code CLI (_bundled/claude); we install from sdist (--no-binary) so
# the image carries ONLY the *Python SDK* surface stanok.py imports against
# (ClaudeAgentOptions, ClaudeSDKClient, message types). stanok.py's
# cli_path resolves `claude` on PATH — inside the container that is the
# baked-in /usr/local/bin/claude (Node.js + CLI section below); without it
# the SDK has no bundled fallback and the launch fails closed.
# Bump it deliberately when you upgrade, not by accident on a rebuild.
ARG CLAUDE_AGENT_SDK_VERSION=0.2.139

# Image provenance: setup.sh computes sha256(Dockerfile + scripts/run.sh)
# and passes it as --build-arg STANOK_DIGEST. The launcher's host-side
# preflight (stanok.py preflight_image, rc=25) re-computes the same digest
# at launch and fails closed on a mismatch — an image older than the
# Dockerfile/STACKS registry becomes a 1-second launch failure instead of
# a mid-run ENV-FAIL.
ARG STANOK_DIGEST=
LABEL stanok.digest="${STANOK_DIGEST}"

# --- OS packages -------------------------------------------------------------
# git                     — model needs read access to history/blame; real
#                           work often needs `git log`/`git blame`, and write
#                           access is blocked at the mount layer (launcher/sandbox.py),
#                           not by withholding the binary — see SEC-01 note there.
# ca-certificates, curl   — outbound goes through http(s)_proxy/no_proxy env
#                           vars set at `docker run`, same policy as before.
#                           Docker adds no network sandboxing of its own here;
#                           --network=host is used to preserve loopback
#                           reachability to the local llama-server, exactly
#                           matching what bwrap already did (it never
#                           unshared the network namespace either — see
#                           launcher/sandbox.py comment on --network).
# build-essential         — most "curl | sh" language installers and native
#                           npm/pip packages with C extensions need a compiler.
# python3/venv            — (a) runs the launcher itself, (b) gives
#                           Python-stack tickets a working interpreter with
#                           zero extra setup. Package management is uv
#                           (baked in below), not pip.
# bubblewrap              — the claude-code NATIVE sandbox (settings.stanok.json
#                           sandbox.enabled=true) shells out to `bwrap` per Bash
#                           command. Without it failIfUnavailable=true hard-fails
#                           the CLI at startup. Runs INSIDE the container (B1
#                           hybrid): needs --security-opt seccomp=unconfined +
#                           apparmor=unconfined at docker run (see
#                           launcher/sandbox.py) and enableWeakerNestedSandbox=true
#                           (skips --proc /proc, which EPERMs in a container).
# socat                   — the CLI's network bridge (allowedDomains) forwards
#                           the sandbox's HTTP/SOCKS bridge sockets via socat;
#                           the CLI hard-fails at startup without it (verified:
#                           "dependencies are missing: socat not installed").
RUN apt-get update && apt-get install -y --no-install-recommends \
      git \
      ca-certificates \
      curl \
      build-essential \
      bubblewrap \
      socat \
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
# --no-binary: build from sdist, NOT the wheel — the wheel ships
# _bundled/claude (a second CLI, ~300 MB). The sdist build has no _bundled
# dir; cli_path (stanok.py) always points at the host binary.
# pytest — the py stack's test-runner in scripts/run.sh is
# `uv run --no-project pytest -q -p no:cacheprovider`; Python-stack tickets
# run their suites with it. Pin deliberately (same rule as the SDK): an
# unpinned install drifts on every rebuild, and a missing pytest in the
# image is exactly the ENV-FAIL class that run.sh's rc=6 and the launcher's
# rc=25 image preflight exist to catch.
RUN uv pip install --no-binary claude-agent-sdk \
      "claude-agent-sdk==${CLAUDE_AGENT_SDK_VERSION}" \
      "pytest==8.3.3"

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
RUN chmod +x /opt/claude-code-2.1.88/cli.js \
    && ln -s /opt/claude-code-2.1.88/cli.js /usr/local/bin/claude

# --- Non-root user -------------------------------------------------------
# Mirrors stanok.py's own root_refusal() host-side check: the container must
# not run the model as root either, or a container escape and a host-level
# root compromise become the same bug instead of two separate ones.
# launcher/sandbox.py additionally passes --user "$(id -u):$(id -g)" at runtime so
# files written into the bind-mounted src/tests/docs/scripts/evidence land
# owned by the invoking host user, not this baked-in UID; this UID is only
# the sane default for anyone who runs the image directly/interactively
# without that override.
RUN groupadd -g "$STANOK_GID" stanok \
    && useradd -m -u "$STANOK_UID" -g "$STANOK_GID" -s /bin/bash stanok

WORKDIR /work
USER stanok

# No ENTRYPOINT/CMD on purpose. launcher/sandbox.py always passes the full command
# explicitly (python3 launcher/stanok.py run ...). An implicit default here
# would be a second, easy-to-forget place the launch command could drift
# from what launch.sh actually invokes — the same class of bug as the
# README/CLAUDE.md drift found earlier in this project.
