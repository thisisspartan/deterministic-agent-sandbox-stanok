# syntax=docker/dockerfile:1
#
# stanok machine image — stack-agnostic worker container.
#
# Design decision (replaces bwrap + bash-gate + read-guard + custom `run` MCP
# tool from waves 1-3): the model gets native Bash back. The security boundary
# moves from "approve every command in advance" to "one strong container +
# resource limits + external, unwritable verification" — see sandbox-run.sh
# for the runtime side of that boundary.
#
# This image deliberately does NOT bake in claude-code or a matching Node
# runtime for it. That binary is bind-mounted read-only from the HOST at
# container start (sandbox-run.sh), pinned to whatever CLI version the
# operator has already validated — throughout this project that has been
# 2.1.88, grepped and verified directly, not assumed from docs. Baking a
# second, independently-versioned claude-code inside the image would
# reintroduce exactly the kind of drift this project has spent several
# review rounds eliminating (README/CLAUDE.md disagreeing about what's
# actually running). Bind-mount, don't reinstall.
#
# What IS baked in: the launcher's own Python runtime (claude-agent-sdk) and
# a minimal, generic toolchain so the MODEL can build/test ANY project stack
# via native Bash — python3/pip/venv out of the box. Everything else (Go,
# Rust, JVM, ...) is one apt-get/curl line added here the day a real ticket
# actually needs it. Do not pre-guess every stack the project might ever use.

FROM debian:bookworm-slim

ARG STANOK_UID=10001
ARG STANOK_GID=10001
# Pin deliberately. Each claude-agent-sdk release bundles a specific Claude
# Code CLI build (0.2.139 -> CLI 2.1.233, at time of writing) but stanok.py
# points cli_path at the bind-mounted HOST claude binary instead (see
# sandbox-run.sh), so this pin only fixes the *Python SDK* surface stanok.py
# imports against (ClaudeAgentOptions, ClaudeSDKClient, message types).
# Bump it deliberately when you upgrade, not by accident on a rebuild.
ARG CLAUDE_AGENT_SDK_VERSION=0.2.139

# --- OS packages -------------------------------------------------------------
# git                     — model needs read access to history/blame; real
#                           work often needs `git log`/`git blame`, and write
#                           access is blocked at the mount layer (sandbox-run.sh),
#                           not by withholding the binary — see SEC-01 note there.
# ca-certificates, curl   — outbound goes through http(s)_proxy/no_proxy env
#                           vars set at `docker run`, same policy as before.
#                           Docker adds no network sandboxing of its own here;
#                           --network=host is used to preserve loopback
#                           reachability to the local llama-server, exactly
#                           matching what bwrap already did (it never
#                           unshared the network namespace either — see
#                           sandbox-run.sh comment on --network).
# build-essential         — most "curl | sh" language installers and native
#                           npm/pip packages with C extensions need a compiler.
# python3/pip/venv        — (a) runs the launcher itself, (b) gives
#                           Python-stack tickets a working interpreter with
#                           zero extra setup.
# bubblewrap              — the claude-code NATIVE sandbox (settings.stanok.json
#                           sandbox.enabled=true) shells out to `bwrap` per Bash
#                           command. Without it failIfUnavailable=true hard-fails
#                           the CLI at startup. Runs INSIDE the container (B1
#                           hybrid): needs --security-opt seccomp=unconfined +
#                           apparmor=unconfined at docker run (see
#                           sandbox-run.sh) and enableWeakerNestedSandbox=true
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
      python3-pip \
      python3-venv \
    && rm -rf /var/lib/apt/lists/*

# --- Launcher runtime ---------------------------------------------------
RUN pip install --break-system-packages --no-cache-dir \
      "claude-agent-sdk==${CLAUDE_AGENT_SDK_VERSION}"

# --- Non-root user -------------------------------------------------------
# Mirrors stanok.py's own root_refusal() host-side check: the container must
# not run the model as root either, or a container escape and a host-level
# root compromise become the same bug instead of two separate ones.
# sandbox-run.sh additionally passes --user "$(id -u):$(id -g)" at runtime so
# files written into the bind-mounted src/tests/docs/scripts/evidence land
# owned by the invoking host user, not this baked-in UID; this UID is only
# the sane default for anyone who runs the image directly/interactively
# without that override.
RUN groupadd -g "$STANOK_GID" stanok \
    && useradd -m -u "$STANOK_UID" -g "$STANOK_GID" -s /bin/bash stanok

WORKDIR /work
USER stanok

# No ENTRYPOINT/CMD on purpose. sandbox-run.sh always passes the full command
# explicitly (python3 launcher/stanok.py run ...). An implicit default here
# would be a second, easy-to-forget place the launch command could drift
# from what launch.sh actually invokes — the same class of bug as the
# README/CLAUDE.md drift found earlier in this project.
