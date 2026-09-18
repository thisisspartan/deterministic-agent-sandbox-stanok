#!/usr/bin/env bash
set -euo pipefail

# stanok sandbox — Docker edition.
#
# Replaces the bwrap version. Kept as the SAME filename and the SAME calling
# contract (`exec "$SANDBOX" "$@"`, launch.sh unchanged) on purpose: this is
# a boundary-implementation swap, not an interface change. Everything above
# this script (launch.sh, stanok.py, CLAUDE.md's contract, summary.json,
# verify_gate on the host) is unaware whether the machine ran under bwrap or
# Docker, which is exactly why this swap is safe to make in isolation.
#
# What changed vs. the bwrap version, and why:
#   - The model gets native Bash back. No bash-gate, no read-guard, no
#     custom `run` MCP tool. The security boundary is the container itself
#     plus resource limits, not a per-command allowlist.
#   - verify_gate() on the HOST is untouched and still authoritative — the
#     container can lie to itself all it wants mid-session, summary.json is
#     only ever written from what the host independently re-runs.
#   - scripts/ is now a writable carve-out (project-owned test entrypoint,
#     see CLAUDE.md) instead of read-only project infrastructure. This is
#     what actually removes the Node lock-in: stanok itself no longer knows
#     or cares what language backs `scripts/run.sh {list,test,smoke} <path>`.

REPO_ROOT="${STANOK_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
LOG_DIR="${STANOK_LOG_DIR:-/tmp/stanok-logs}"
mkdir -p "$LOG_DIR"

if ! command -v docker &>/dev/null; then
    echo "ERROR: docker not found on PATH" >&2
    exit 1
fi

IMAGE="${STANOK_DOCKER_IMAGE:-stanok-machine:latest}"

# --- Pin the host's claude + node install, bind-mounted read-only ----------
# Same reasoning as the bwrap version's host-binary discovery: the image does
# NOT bundle its own claude-code, so whichever CLI the operator has already
# validated (STANOK_CLAUDE_BIN, or `claude` on PATH) is what runs inside the
# container too. Zero version drift between "what I greped" and "what ran".
HOST_CLAUDE="${STANOK_CLAUDE_BIN:-$(command -v claude || true)}"
if [ -z "$HOST_CLAUDE" ]; then
    echo "ERROR: claude CLI not found (set STANOK_CLAUDE_BIN or add to PATH)" >&2
    exit 1
fi
HOST_CLAUDE_SHIM_DIR="$(dirname "$HOST_CLAUDE")"

# The claude install can be a MULTI-HOP symlink chain (verified on this
# host: bin/claude -> .npm-global/lib/node_modules/.../cli.js ->
# git/claude-code-2.1.88/cli.js). Every directory a hop lives in must be
# bind-mounted, or an intermediate hop dangles inside the container and
# `command -v claude` fails. Scope stays narrow: only the chain's own
# directories — never a broader parent that could be a user's git checkout
# root leaking unrelated repos.
CLAUDE_MOUNT_DIRS=()
_hop="$HOST_CLAUDE"
while :; do
    _d="$(dirname "$_hop")"
    case " ${CLAUDE_MOUNT_DIRS[*]} " in *" $_d "*) : ;; *) CLAUDE_MOUNT_DIRS+=("$_d") ;; esac
    [ -L "$_hop" ] || break
    _next="$(readlink "$_hop")"
    case "$_next" in /*) : ;; *) _next="$_d/$_next" ;; esac
    _hop="$_next"
done
CLAUDE_MOUNTS=()
for _d in "${CLAUDE_MOUNT_DIRS[@]}"; do
    CLAUDE_MOUNTS+=(-v "$_d:$_d:ro")
done

HOST_NODE="$(command -v node || true)"
NODE_MOUNTS=()
if [ -n "$HOST_NODE" ]; then
    HOST_NODE_REAL="$(readlink -f "$HOST_NODE")"
    # File-level mount: a directory mount of the node dir (e.g. /usr/bin)
    # would overlay the image's /usr/bin and break the image python3 and
    # the venv python the launcher runs.
    NODE_MOUNTS+=(-v "$HOST_NODE_REAL:/usr/local/bin/node:ro")
fi

mkdir -p "$REPO_ROOT/src" "$REPO_ROOT/tests" "$REPO_ROOT/docs" \
         "$REPO_ROOT/scripts" "$REPO_ROOT/evidence"

# --- Writable carve-outs -----------------------------------------------
# Base repo mounted read-only; specific subpaths re-mounted rw on top
# (Docker layers -v mounts by specificity, same effect as bwrap's ordered
# --ro-bind / --bind pairs). .git inherits :ro from the base mount — no
# separate line needed; `git status/log/blame/diff` work, `git commit`
# fails at the filesystem layer exactly like before (SEC-01, unchanged).
# Parent of the repo mounted ro FIRST: tickets live in $PARENT_DIR/tickets
# (stanok.py resolves them against dirname(REPO_ROOT)) and the role-leak
# gate (rc=24) checks $PARENT_DIR/CLAUDE.md — both invisible without this.
PARENT_DIR="$(dirname "$REPO_ROOT")"
VOLUME_ARGS=(
  -v "$PARENT_DIR:$PARENT_DIR:ro"
  -v "$REPO_ROOT:$REPO_ROOT:ro"
  -v "$REPO_ROOT/src:$REPO_ROOT/src:rw"
  -v "$REPO_ROOT/tests:$REPO_ROOT/tests:rw"
  -v "$REPO_ROOT/docs:$REPO_ROOT/docs:rw"
  -v "$REPO_ROOT/scripts:$REPO_ROOT/scripts:rw"
  -v "$REPO_ROOT/evidence:$REPO_ROOT/evidence:rw"
  -v "$LOG_DIR:$LOG_DIR:rw"
  "${CLAUDE_MOUNTS[@]}"
  "${NODE_MOUNTS[@]}"
)

# --- Env passthrough -----------------------------------------------------
# stanok.py itself only reads STANOK_* (see build_agent_env() — deliberately
# minimal, "Prefix Invariance"). Everything static (CLAUDE_CODE_* feature
# flags, retries, timeouts) lives in .claude/settings.stanok.json and is
# loaded natively by claude-code at startup — that file is already inside
# the read-only $REPO_ROOT mount, nothing extra to pass for it.
# http(s)_proxy/no_proxy now matter for real: Bash is native, so `pip
# install`/`npm install`/`curl` inside the container need to know how to
# reach the network the same way the rest of this project already does.
ENV_ARGS=()
for var in $(compgen -v | grep '^STANOK_'); do
    ENV_ARGS+=(-e "${var}=${!var}")
done
# node is mounted at /usr/local/bin/node; the claude CLI is launched via an
# absolute path (STANOK_CLAUDE_BIN), but both dirs go on PATH so the shim's
# `#!/usr/bin/env node` shebang and any interactive use resolve.
ENV_ARGS+=(-e "PATH=/usr/local/bin:${HOST_CLAUDE_SHIM_DIR}:/usr/bin:/bin")
# Ephemeral HOME on a tmpfs (decision §2.1): no host coupling, the CLI's
# ~/.claude and ~/.claude.json live and die with the container.
ENV_ARGS+=(-e "HOME=/home/stanok")
# Host-namespace pid of THIS process (the docker CLI stays alive while the
# container runs) — stanok.py's marker pid must be visible to the host-side
# `launch.sh status` or the supervisor's blocking wait breaks.
ENV_ARGS+=(-e "STANOK_HOST_PID=$$")
for var in http_proxy https_proxy no_proxy NO_PROXY; do
    if [ -n "${!var:-}" ]; then
        ENV_ARGS+=(-e "${var}=${!var}")
    fi
done

# --- Resource limits -------------------------------------------------------
# New vs. the bwrap version, and necessary now: with Bash unrestricted the
# realistic risk is an accident (fork bomb, runaway build, filled disk), not
# deliberate escape. This is defense in depth alongside the existing
# Python-level TURN_TIMEOUT_S watchdog in stanok.py, not a replacement for it.
RESOURCE_ARGS=(
  --memory="${STANOK_CONTAINER_MEM:-4g}"
  --pids-limit="${STANOK_CONTAINER_PIDS:-512}"
  --cpus="${STANOK_CONTAINER_CPUS:-2}"
)

# --- Hardening that costs nothing behaviorally ------------------------------
# seccomp/apparmor UNCONFINED: required for the claude-code native sandbox
# (bwrap) to run INSIDE the container (B1 hybrid) — docker's default seccomp
# blocks unshare, its default AppArmor blocks "make / slave". Verified
# empirically 2026-09-18 (see specs/PLAN-DOCKER-REFACTOR.md §5). The per-command
# bwrap user-namespace sandbox + cap-drop=ALL + no-new-privileges remain the
# effective boundary; the docker profiles are the layer we trade away.
SECURITY_ARGS=(
  --cap-drop=ALL
  --security-opt=no-new-privileges
  --security-opt seccomp=unconfined
  --security-opt apparmor=unconfined
  --user "$(id -u):$(id -g)"
)

CONTAINER_NAME="stanok-$(basename "$REPO_ROOT")-$$"

# --- Reaper: forward signals to `docker stop`, always clean up -------------
# Docker has no --die-with-parent equivalent: a killed launch.sh does NOT by
# itself stop the container. This trap is what makes "kill the launcher ->
# kill everything" true again, matching the bwrap version's guarantee and
# stanok.py's own "Process Reaper" design goal.
cleanup() {
    docker stop -t 5 "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# --network=host: loopback reachability to the local llama-server
# (STANOK_SERVER_URL, typically 127.0.0.1:8080). The bwrap version never
# isolated the network namespace either — --unshare-net was explicitly
# rejected earlier in this project for the same reason (it breaks loopback
# to the inference server). No new exposure versus before; same trust
# boundary, different mechanism.
# No `exec`: it would replace this shell and discard the cleanup trap,
# leaving the container orphaned when the launcher dies. Run docker as a
# child; set -e propagates its exit code and the EXIT trap fires either way.
#
# Launcher python: the host's $1 is normally $REPO_ROOT/.venv/bin/python —
# a symlink to /usr/bin/python3. Inside the container that symlink lands on
# the IMAGE's python (3.11), but the venv's pyvenv.cfg and site-packages
# were built for the host's python (3.12) and the venv dir is read-only —
# the venv is unusable in the container and `import claude_agent_sdk`
# fails. The Dockerfile bakes the SDK into the image's system python on
# purpose: run that directly (same binary, no venv confusion).
case "$1" in
    "$REPO_ROOT/.venv/bin/python")
        set -- /usr/bin/python3 "${@:2}" ;;
    /*)
        [ -x "$1" ] || set -- /usr/bin/python3 "${@:2}" ;;
esac
docker run --rm \
  --name "$CONTAINER_NAME" \
  --init \
  --network=host \
  --tmpfs "/home/stanok:uid=$(id -u),gid=$(id -g),mode=700" \
  -w "$REPO_ROOT" \
  "${VOLUME_ARGS[@]}" \
  "${ENV_ARGS[@]}" \
  "${RESOURCE_ARGS[@]}" \
  "${SECURITY_ARGS[@]}" \
  "$IMAGE" \
  "$@"
