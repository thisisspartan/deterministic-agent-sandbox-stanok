"""gates — the launch gates (PLAN-HYGIENE 2026-10-08 split, step 5).

Label guard, role-leak refusal, dirty-tree, hidden-files, test-config (CC-151),
sandbox-config, the server/image preflights and the context-window derivation.
The repo root and server URL come from the passed-in Config (C).
_DERIVED_REQUIRED_WINDOW is a module global (written by preflight_server, read
by context_rot_threshold); tests_harness monkeypatches this module's functions
directly — Python resolves module globals at call time, so patching works.
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
import tomllib
from launcher import sandbox
from launcher.logs import log

_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


# ==================================================================================
# Sanitary control and gates
# ==================================================================================
def validate_label(label: str) -> str | None:
    if not _LABEL_RE.match(label) or ".." in label or label.startswith("--"):
        return f"label {label!r} contains invalid characters"
    return None


def root_refusal() -> None:
    if os.geteuid() == 0:
        log("ABORT: running as root is forbidden")
        sys.exit(1)


def dirty_tree_gate(cfg) -> bool:
    # Fail-closed: a git error means the tree state is UNKNOWN -> treat as dirty.
    try:
        out = subprocess.run(["git", "status", "--porcelain"],
                             cwd=cfg.repo_root, capture_output=True, text=True)
        if out.returncode != 0:
            log("WARN: git status failed in dirty_tree_gate — fail-closed (treating as dirty)")
            return True
        return bool(out.stdout.strip())
    except OSError:
        log("WARN: git status raised in dirty_tree_gate — fail-closed (treating as dirty)")
        return True


def hidden_files_gate(cfg) -> bool:
    # W4 hygiene gate (fail-closed): reject a launch if src/tests/docs/scripts
    # holds, at ANY DEPTH, a hidden file or directory (name starting with '.',
    # except .gitkeep) or a file carrying a 'TEMP:' marker in its first 40
    # lines. Such leftovers from past runs leak into the machine's context (the
    # model reads them and derives requirements from them) and slip past
    # dirty_tree_gate (git status is clean for committed/ignored dotfiles).
    # Intentionally narrow (owner decision): only these two signals, not "any
    # undeclared file".
    #
    # CC-139: this used to os.listdir only the zone TOP level, so a hidden
    # leftover in a subdirectory (`src/pkg/.secret`) was invisible (audit
    # Appendix A #3). The walk is recursive; a hidden DIRECTORY is flagged too,
    # since it is the same class of leftover and a dot-dir holding only
    # non-hidden files (src/.cache/notes.md) would otherwise still leak.
    for d in sandbox.WRITABLE_ZONES:
        dirpath = os.path.join(cfg.repo_root, d)
        if not os.path.isdir(dirpath):
            continue
        walk_errors: list[OSError] = []
        for root, dirs, files in os.walk(dirpath, onerror=walk_errors.append):
            for name in dirs:
                if name.startswith(".") and name != ".gitkeep":
                    log(f"HIDDEN-DIR: {os.path.join(root, name)}")
                    return True
            for name in files:
                path = os.path.join(root, name)
                if name.startswith(".") and name != ".gitkeep":
                    log(f"HIDDEN-FILE: {path}")
                    return True
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        head = [f.readline() for _ in range(40)]
                except OSError:
                    log(f"WARN: read failed in hidden_files_gate for {path} — fail-closed (treating as flagged)")
                    return True
                if any("TEMP:" in line for line in head):
                    log(f"TEMP-MARKER: {path}")
                    return True
        if walk_errors:
            log(f"WARN: walk failed in hidden_files_gate under {dirpath}: "
                f"{walk_errors[0]} — fail-closed (treating as flagged)")
            return True
    return False


def zone_symlinks(cfg) -> list[str]:
    """All symlinks under the writable zones — the ONE scanner shared by the
    launch gate (zone_symlink_gate) and the post-turn check
    (verify._check_zone_symlinks). The rule (cc217 review follow-up, operator
    decision 2026-10-09): in src/tests/docs/scripts symlinks do not exist.

    lstat semantics: os.walk with followlinks=False (a symlinked directory is
    LISTED, never descended into) and os.path.islink on every entry — file
    links, directory links and dangling links are all found; the zone
    directory itself is checked too (`src -> launcher/` — no walk would see
    its contents as zone content). Raises OSError on a walk error (callers
    fail closed)."""
    found: list[str] = []
    for d in sandbox.WRITABLE_ZONES:
        dirpath = os.path.join(cfg.repo_root, d)
        if os.path.islink(dirpath):
            found.append(d)
            continue
        if not os.path.isdir(dirpath):
            continue
        walk_errors: list[OSError] = []
        for root, dirs, files in os.walk(dirpath, followlinks=False,
                                         onerror=walk_errors.append):
            for name in dirs + files:
                path = os.path.join(root, name)
                if os.path.islink(path):
                    found.append(os.path.relpath(path, cfg.repo_root))
        if walk_errors:
            raise walk_errors[0]
    return sorted(found)


def zone_symlink_gate(cfg) -> list[str]:
    """The zone-symlink ban at launch (rc=13, wired in cli._launch_gates):
    no symlink may exist in src/tests/docs/scripts. The container mounts the
    repo :ro and derives rw carve-outs only inside the zones; Docker resolves
    a bind source's realpath, so a link hands rw access to its TARGET
    (`src/link -> launcher/` — proven by test_docker_bind_resolves_symlink_source).
    The ban covers UNDECLARED links (the declared-path rule inspects only
    declared paths) and links under tests/ (host_ro_paths would bind them
    :ro verbatim and Docker would resolve them to their targets). The
    post-run counterpart is verify._check_zone_symlinks (CONTRACT-FAIL).

    Returns the problem list (empty = OK); each problem names the path, its
    target and the fix — an accidental operator-side symlink must come with
    an actionable message. A scan error RAISES: a broken filesystem is not the
    ticket's fault, the caller maps it to the infrastructure rc (ENV-FAIL,
    rc=16), not to rc=13 (operator review 2026-10-09)."""
    links = zone_symlinks(cfg)
    problems: list[str] = []
    for rel in links:
        target = os.readlink(os.path.join(cfg.repo_root, rel))
        problems.append(
            f"{rel} -> {target}: replace the symlink with a regular "
            f"file/directory — Docker resolves a bind source's realpath, "
            f"so a symlink escapes the writable-zone boundary")
    for p in problems:
        log(f"ZONE-SYMLINK: {p}")
    return problems


# CC-151: the pre-manifest (W6) py verdict-config set. Fail-closed fallback
# when no stack manifest parses (e.g. hermetic test repos with no
# scripts/stacks/), so the guard never silently disables.
_LEGACY_VERDICT_CONFIG = ("conftest.py", "pytest.ini", "tox.ini",
                         "setup.cfg", "pyproject.toml")


def _stack_manifests(cfg) -> tuple[dict[str, dict], bool]:
    """Parse the STACK REGISTRY manifests (scripts/stacks/*.toml, sorted by
    filename) via tomllib — the SINGLE parser for the manifests (run.sh
    derives its STACKS lines with the same tomllib, no codegen). Returns
    ({filename: data}, ok); ok is False when no manifest parsed (missing dir,
    unparseable TOML, or tomllib unavailable) — callers fail closed on that."""
    if tomllib is None:
        return {}, False
    stacks_dir = os.path.join(cfg.repo_root, "scripts", "stacks")
    out: dict[str, dict] = {}
    ok = True
    try:
        entries = sorted(os.listdir(stacks_dir))
    except OSError:
        entries = []
    for entry in entries:
        if not entry.endswith(".toml"):
            continue
        path = os.path.join(stacks_dir, entry)
        try:
            with open(path, "rb") as f:
                out[entry] = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            log(f"WARN: stack manifest {entry} unreadable: {e}")
            ok = False
    if not out:
        ok = False
    return out, ok


def _verdict_config_patterns(cfg) -> tuple[str, ...]:
    """CC-151 (stack-agnostic subversion guard): the union of the
    `verdict_config` lists declared by the stack manifests
    (scripts/stacks/*.toml). Each stack declares the config filenames that
    can rewrite ITS runner's verdict (py: the pytest config set; js/jq: none).
    The manifest is authoritative — a stack that declares no verdict_config
    does not inherit another stack's list. Fail-closed: if no manifest parses
    (missing dir, unparseable TOML, or tomllib unavailable) fall back to the
    legacy py set so the guard never silently disables."""
    manifests, ok = _stack_manifests(cfg)
    if not ok:
        return _LEGACY_VERDICT_CONFIG
    patterns: set[str] = set()
    for data in manifests.values():
        for name in data.get("verdict_config", []):
            if isinstance(name, str) and name:
                patterns.add(name)
    return tuple(sorted(patterns))


def check_test_config(cfg) -> bool:
    # W6 verdict-subversion gate (owner decision A, fail-closed); CC-151 makes
    # it stack-agnostic: the forbidden set is the union of the `verdict_config`
    # lists declared by the stack manifests (scripts/stacks/*.toml), not a
    # hardcoded py tuple. A config file that can rewrite a runner's verdict
    # (e.g. a conftest.py with `pytest_sessionfinish: session.exitstatus = 0`
    # turning a failing test into rc=0) is rejected at launch (rc=27). tests/
    # is writable and contract_lock only hashes files that existed at start,
    # so such a file can appear mid-project; the runner picks up config from
    # every directory on the test file's path, hence the recursive walk.
    tests_dir = os.path.join(cfg.repo_root, "tests")
    if not os.path.isdir(tests_dir):
        return False
    forbidden = _verdict_config_patterns(cfg)
    try:
        for dirpath, _dirnames, filenames in os.walk(tests_dir):
            for name in filenames:
                if name in forbidden:
                    log(f"TEST-CONFIG: {os.path.join(dirpath, name)}")
                    return True
    except OSError:
        log("WARN: walk failed in check_test_config — fail-closed (treating as flagged)")
        return True
    return False


def sandbox_config_gate(cfg) -> list[str]:
    # W7 sandbox-config gate (fail-closed, CC-107): cli.js resolves a relative
    # sandbox.filesystem deny entry against the --settings file's directory
    # (REPO_ROOT/.claude), NOT cwd. A deny entry that resolves to a NON-EXISTENT
    # path makes cli.js emit `--ro-bind /dev/null <path>`; bwrap must create the
    # mount point, and on the read-only repo mount that is EROFS for EVERY Bash
    # call in the session (CC-107). A non-existent deny entry is always a mistake
    # (typo / wrong base), so fail-closed if any denyWrite/denyRead entry does
    # not exist.
    #
    # We do NOT reimplement cli.js's resolver: this config only uses
    # settings-relative entries (written "../<name>" from .claude) and absolute
    # paths. Any other form ("~", "//") is rejected rather than guessed at, so
    # the gate cannot silently diverge from cli.js semantics.
    #
    # Returns a list of human-readable problems (empty = OK). Each problem
    # names the key, the raw entry, the resolved path, and the fix
    # (CC-157: the rc=28 abort must be actionable, not abstract).
    problems: list[str] = []
    settings = os.path.join(cfg.repo_root, ".claude", "settings.stanok.json")
    if not os.path.isfile(settings):
        return problems
    try:
        with open(settings, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        problems.append(f"could not parse {settings}: {e}")
        return problems
    base = os.path.dirname(settings)  # == REPO_ROOT/.claude (cli.js flagSettings root)
    fs = cfg.get("sandbox", {}).get("filesystem", {})
    for key in ("denyWrite", "denyRead"):
        for entry in fs.get(key, []):
            if entry.startswith(("~", "//")):
                problems.append(
                    f"{key} entry {entry!r} is not settings-relative/absolute (unsupported)")
                continue
            resolved = entry if os.path.isabs(entry) else os.path.normpath(os.path.join(base, entry))
            if not os.path.exists(resolved):
                problems.append(
                    f"{key} entry {entry!r} resolves to non-existent {resolved} "
                    f"(base {base}) — fix: mkdir -p {resolved}")
    for p in problems:
        log(f"SANDBOX-CONFIG: {p}")
    return problems


# Safety margin between the server's live n_ctx and the derived required
# window when STANOK_REQUIRED_WINDOW is not set (preflight_server).
REQUIRED_WINDOW_MARGIN = 2000

# The required window derived from the live server by preflight_server when
# STANOK_REQUIRED_WINDOW is unset. Single source (PLAN-HYGIENE 2026-10-08):
# context_rot_threshold reads this instead of a hardcoded default — the old
# `or 128000` silently overrode the real window when the env was unset.
_DERIVED_REQUIRED_WINDOW: int | None = None


def _required_context_window() -> int | None:
    """Required context window, from the env only: STANOK_REQUIRED_WINDOW
    (exported by P0-launch.sh). cli.js likewise reads
    CLAUDE_CODE_AUTO_COMPACT_WINDOW from env (rQ); there is no settings source —
    the former .claude/settings.stanok.json fallback read a key that no longer
    exists (CC-127). When the env var is unset, preflight_server derives the
    required window from the live server (n_ctx - REQUIRED_WINDOW_MARGIN)
    instead of skipping the check — a stale env number must not be the only
    thing standing between a healthy server and rc=20 (incident
    smoke-cc183-retry1: env 128000 vs server n_ctx 125184). The derived
    value is stored in _DERIVED_REQUIRED_WINDOW for the consumers that need
    a window without re-reading /props."""
    env_val = os.environ.get("STANOK_REQUIRED_WINDOW")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            log(f"WARN: STANOK_REQUIRED_WINDOW={env_val!r} is not an integer; ignoring")
    return None


def context_rot_threshold() -> int | None:
    """Warn threshold for the live context window (tokens on the LAST API call).
    Env STANOK_CONTEXT_ROT_TOKENS wins; otherwise 80% of the required window —
    the point where attention on a long prompt visibly degrades. The window
    has ONE source (PLAN-HYGIENE 2026-10-08): env STANOK_REQUIRED_WINDOW, else
    the value preflight_server derived from the live /props. None when no
    window is known — the caller skips the WARN rather than inventing a
    default."""
    env = os.environ.get("STANOK_CONTEXT_ROT_TOKENS")
    if env:
        try:
            return int(env)
        except ValueError:
            log(f"WARN: STANOK_CONTEXT_ROT_TOKENS={env!r} is not an integer; ignoring")
    window = _required_context_window()
    if window is None:
        window = _DERIVED_REQUIRED_WINDOW
    if window is None:
        return None
    return int(window * 0.8)


def _fetch_server_props(cfg) -> dict | None:
    """GET {cfg.server_url}/props (no proxy, 5 s timeout). None on any failure."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(f"{cfg.server_url}/props"), timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        log(f"SERVER UNAVAILABLE ({cfg.server_url}: {type(e).__name__}) (rc=20)")
        return None


def preflight_server(cfg) -> bool:
    global _DERIVED_REQUIRED_WINDOW
    if os.environ.get("STANOK_SKIP_SERVER_CHECK") == "1":
        return True
    props = _fetch_server_props(cfg)
    if props is None:
        return False

    n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
    if not isinstance(n_ctx, int) or n_ctx <= 0:
        log(f"PREFLIGHT: unparseable n_ctx in /props (fail-closed) (rc=20)")
        return False

    required = _required_context_window()
    if required is None:
        # No hard window in env — derive it from the live server so the check
        # tracks the actual n_ctx instead of a possibly stale env number.
        required = n_ctx - REQUIRED_WINDOW_MARGIN
        if required <= 0:
            log(f"PREFLIGHT: server n_ctx={n_ctx} <= margin {REQUIRED_WINDOW_MARGIN} (fail-closed) (rc=20)")
            return False
        _DERIVED_REQUIRED_WINDOW = required
        log(f"PREFLIGHT: STANOK_REQUIRED_WINDOW unset — derived required window "
            f"{required} (n_ctx {n_ctx} - margin {REQUIRED_WINDOW_MARGIN})")
    if n_ctx < required:
        log(f"PREFLIGHT: server n_ctx={n_ctx} < required window {required} (rc=20)")
        return False
    log(f"PREFLIGHT: server n_ctx={n_ctx} >= required window {required} — OK")
    return True


def _stack_preflights(cfg) -> list[str]:
    """The `preflight` command of each stack manifest (scripts/stacks/*.toml,
    sorted by filename) — the cheap per-stack runner-availability probe
    (e.g. `env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --version`).
    Read via the same tomllib loader as _verdict_config_patterns — NOT a
    regex over run.sh (the pre-CC-148 registry block no longer lives there;
    the old regex silently returned [] and disabled the doctor probe)."""
    manifests, _ok = _stack_manifests(cfg)
    preflights = []
    for data in manifests.values():
        pre = data.get("preflight")
        if isinstance(pre, str) and pre.strip():
            preflights.append(pre.strip())
    return preflights


# The image-defining sources, in the exact order BOTH digest computations
# concatenate them (modernization batch 2, 2026-10-08): setup.sh bakes
# sha256 of these into the image LABEL stanok.digest at build; _image_digest()
# re-computes the same hash in doctor. A glob entry is resolved sorted by
# filename. image-requirements.lock is an input: a dependency-lock change
# must move the digest, or a stale image passes the doctor check while
# carrying a different package set than the tree declares.
# test_image_digest_inputs.py pins that setup.sh's cat list and this tuple
# cannot drift.
DIGEST_INPUTS = ("Dockerfile", "scripts/run.sh", "scripts/stacks/*.toml", "image-requirements.lock")


def _image_digest(cfg) -> str:
    """sha256 over DIGEST_INPUTS (the single declared list — see above).
    setup.sh bakes this into the image LABEL stanok.digest at build time;
    preflight_image() re-computes it in doctor (CC-106: moved off the
    launch path)."""
    h = hashlib.sha256()
    for pattern in DIGEST_INPUTS:
        if "*" in pattern:
            for path in sorted(glob.glob(os.path.join(cfg.repo_root, pattern))):
                with open(path, "rb") as f:
                    h.update(f.read())
        else:
            with open(os.path.join(cfg.repo_root, pattern), "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def preflight_image(cfg, image: str) -> bool:
    """Host-side image provenance + runner preflight.
    1. The image LABEL stanok.digest must equal sha256 over gates.DIGEST_INPUTS
       (Dockerfile + run.sh + scripts/stacks/*.toml + image-requirements.lock) — an image
       older than the Dockerfile, the STACKS registry or the dependency lock
       is caught here, not mid-run.
    2. Each stack's preflight command must succeed INSIDE the image
       (docker run --rm) — the runner is available where the tests run.
    CC-106: no longer on the launch path (the former blocking rc=25 is
    freed) — doctor calls it (test_doctor.py::test_docker_image_digest_matches).
    Fail-closed: any docker error, missing label, or failed probe returns
    False."""
    try:
        want = _image_digest(cfg)
    except OSError as e:
        log(f"PREFLIGHT-IMAGE: cannot compute image digest: {e} (doctor image preflight)")
        return False
    try:
        out = subprocess.run(
            ["docker", "inspect", "--format",
             '{{index .Config.Labels "stanok.digest"}}', image],
            capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            log(f"PREFLIGHT-IMAGE: image {image} not found (doctor image preflight)")
            return False
        got = out.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        log(f"PREFLIGHT-IMAGE: docker inspect failed: {e} (doctor image preflight)")
        return False
    if got != want:
        log(f"PREFLIGHT-IMAGE: digest mismatch — image label {got!r} != "
            f"sha256(Dockerfile+run.sh+stacks) {want!r}; rebuild via ./setup.sh (doctor image preflight)")
        return False
    log(f"PREFLIGHT-IMAGE: digest OK ({want[:12]}…)")
    for pre in _stack_preflights(cfg):
        try:
            p = subprocess.run(
                ["docker", "run", "--rm", image, "/bin/sh", "-c", pre],
                capture_output=True, text=True, timeout=60)
            if p.returncode != 0:
                log(f"PREFLIGHT-IMAGE: runner unavailable in image: {pre!r} "
                    f"(probe rc={p.returncode}) (doctor image preflight)")
                return False
        except (OSError, subprocess.SubprocessError) as e:
            log(f"PREFLIGHT-IMAGE: docker run failed for {pre!r}: {e} (doctor image preflight)")
            return False
    log("PREFLIGHT-IMAGE: all stack runners available in the image — OK")
    return True

