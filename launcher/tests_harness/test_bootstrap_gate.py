"""CC-150 — bootstrap gate for top-level paths (hermetic).

A NEW top-level file (e.g. `pyproject.toml`) has no existing ancestor to carve
out (declared_carveout -> None), so it cannot be declared `impl:`/`edit:`. The
`bootstrap:` declaration kind creates it, gated by:

  - the path is in the audited per-stack `bootstrap_paths` set
    (scripts/stacks/*.toml) — fail-closed to the EMPTY set when no manifest
    parses (bootstrap is a NEW capability; it never silently widens);
  - the path does not already exist as a NON-EMPTY file (CC-154: the launcher
    pre-creates an EMPTY placeholder, which is allowed);
  - the path cannot escape the repo (relative, no `..`, no symlink out);
  - `scripts/run.sh` is ABSENT and NOT declared in the ticket (CC-154: a
    bootstrap ticket that also wrote the entrypoint would make run.sh
    writable — the verdict-subversion surface the contract lock closes).

CC-154 Variant A: instead of mounting the repo ROOT rw (CC-150), the host
pre-creates an EMPTY placeholder so declared_carveout resolves the bootstrap
path to a single-FILE rw bind — the base repo stays strictly :ro.

Cases:
  1  audited path + run.sh absent            -> allowed
  2  path NOT in audited set                 -> rejected
  3  run.sh present, not declared            -> rejected
  4  run.sh present + declared (edit:)       -> rejected
  5  audited path exists non-empty           -> rejected
  5b audited path exists EMPTY (placeholder) -> allowed
  6  `..` escape                             -> rejected
  7  absolute path                           -> rejected
  8  no manifest (fail-closed)               -> rejected
  9  host_ro_paths dir carve-out             -> re-binds protected files under it
  10 sandbox_argv                            -> repo root always :ro; a bootstrap
                                                file carve-out is a :rw file bind
  11 precreate_bootstrap_paths               -> empty placeholder, idempotent

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_bootstrap_gate.py -q
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = REPO_ROOT / "launcher"

if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402
import sandbox  # noqa: E402

# A py manifest that audits exactly one top-level bootstrap path.
PY_BOOTSTRAP_MANIFEST = 'ext = "py"\nbootstrap_paths = ["pyproject.toml"]\n'


def _repo(tmp_path, files, manifest=None):
    """A hermetic repo: optional manifest at scripts/stacks/py.toml plus the
    given {rel_path: body} files."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        m = repo / "scripts" / "stacks" / "py.toml"
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(manifest, encoding="utf-8")
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return repo


# --- 1: audited path + run.sh absent -> allowed ------------------------------

def test_bootstrap_allowed(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {}, manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    declared, edit, reset, bootstrap = stanok.parse_ticket_header(
        "bootstrap: pyproject.toml\n")
    assert bootstrap == ["pyproject.toml"]
    assert declared == ["pyproject.toml"]
    assert edit == []


# --- 2: path NOT in audited set -> rejected ----------------------------------

def test_bootstrap_not_in_audited_set(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {}, manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    with pytest.raises(ValueError):
        stanok.parse_ticket_header("bootstrap: evil.sh\n")


# --- 3: run.sh present, not declared -> rejected ----------------------------

def test_bootstrap_runsh_present_not_declared(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"scripts/run.sh": "#!/bin/sh\n"},
                manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    with pytest.raises(ValueError):
        stanok.parse_ticket_header("bootstrap: pyproject.toml\n")


# --- 4: run.sh present + declared (edit:) -> rejected (CC-154) ---------------

def test_bootstrap_runsh_declared_rejected(tmp_path, monkeypatch):
    # CC-154: bootstrap must not coexist with a write to the entrypoint —
    # otherwise run.sh becomes writable (verdict-subversion surface).
    repo = _repo(tmp_path, {"scripts/run.sh": "#!/bin/sh\n"},
                manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    with pytest.raises(ValueError):
        stanok.parse_ticket_header(
            "bootstrap: pyproject.toml\nedit: scripts/run.sh\n")


# --- 5: audited path already exists -> rejected -----------------------------

def test_bootstrap_path_exists_rejected(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"pyproject.toml": "[tool]\n"},
                manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    with pytest.raises(ValueError):
        stanok.parse_ticket_header("bootstrap: pyproject.toml\n")


# --- 5b: EMPTY placeholder (pre-created by the launcher) -> allowed ----------

def test_bootstrap_empty_placeholder_allowed(tmp_path, monkeypatch):
    # CC-154: the host pre-creates the path EMPTY before docker run, so the
    # container's re-parse must accept it (a placeholder, not an artifact).
    repo = _repo(tmp_path, {"pyproject.toml": ""},
                 manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    declared, _, _, bootstrap = stanok.parse_ticket_header(
        "bootstrap: pyproject.toml\n")
    assert bootstrap == ["pyproject.toml"]
    assert declared == ["pyproject.toml"]


# --- 6: `..` escape -> rejected ----------------------------------------------

def test_bootstrap_dotdot_rejected(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {}, manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    with pytest.raises(ValueError):
        stanok.parse_ticket_header("bootstrap: ../pyproject.toml\n")


# --- 7: absolute path -> rejected --------------------------------------------

def test_bootstrap_absolute_rejected(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {}, manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    with pytest.raises(ValueError):
        stanok.parse_ticket_header("bootstrap: /etc/passwd\n")


# --- 8: no manifest (fail-closed) -> rejected --------------------------------

def test_bootstrap_no_manifest_denied(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {})  # no scripts/stacks/ -> empty audited set
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    with pytest.raises(ValueError):
        stanok.parse_ticket_header("bootstrap: pyproject.toml\n")


# --- 9: host_ro_paths re-binds protected files under a dir carve-out ---------

def test_host_ro_paths_dir_carveout(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {
        "tests/foo_test.py": "def test_ok():\n    assert True\n",
        "scripts/run.sh": "#!/bin/sh\n",
    })
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    # A `tests` carve-out hands back write access to tests/ -> the pre-existing
    # protected file under it is re-bound :ro; scripts/run.sh is outside it.
    ro = stanok.host_ro_paths([], ("tests",))
    assert set(ro) == {"tests/foo_test.py"}


# --- 10: sandbox_argv — repo always :ro; bootstrap file binds :rw ------------

def test_sandbox_argv_repo_always_ro(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "pyproject.toml").write_text("", encoding="utf-8")
    log_dir = tmp_path / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    # CC-154: the base repo mount is ALWAYS :ro; the pre-created bootstrap file
    # is carved out as a single-FILE :rw bind on top.
    _name, argv = sandbox.sandbox_argv(str(repo), str(log_dir), "img", ["cmd"],
                                       rw_paths=("pyproject.toml",))
    assert f"{repo}:{repo}:ro" in argv
    assert f"{repo}:{repo}:rw" not in argv
    assert f"{repo}/pyproject.toml:{repo}/pyproject.toml:rw" in argv


# --- 11: precreate_bootstrap_paths creates an empty placeholder --------------

def test_precreate_bootstrap_paths(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {}, manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.precreate_bootstrap_paths(["pyproject.toml"]) == 0
    p = repo / "pyproject.toml"
    assert p.is_file() and p.read_text(encoding="utf-8") == ""
    assert (p.stat().st_mode & 0o111) == 0          # never executable
    # Idempotent: an existing (now filled) file is left untouched.
    p.write_text("x\n", encoding="utf-8")
    assert stanok.precreate_bootstrap_paths(["pyproject.toml"]) == 0
    assert p.read_text(encoding="utf-8") == "x\n"
    # A pre-created placeholder makes declared_carveout resolve to the file.
    assert stanok.declared_carveout("pyproject.toml") == "pyproject.toml"


# --- 12: docker e2e — the mount boundary (skipped without docker/image) ------

_IMAGE = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "image", "inspect", _IMAGE],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="docker + machine image required")
def test_bootstrap_mount_boundary_e2e(tmp_path, monkeypatch):
    """CC-154 Variant A end to end: the base repo is strictly :ro; only the
    pre-created bootstrap placeholder is writable; launcher/, hooks/, .claude/,
    Dockerfile and scripts/run.sh are all EROFS."""
    repo = tmp_path / "repo"
    for d in ("launcher", "hooks", ".claude", "docs", "src", "tests", "scripts"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    for f in ("Dockerfile", "CLAUDE.md", "setup.sh", "scripts/run.sh"):
        (repo / f).write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.precreate_bootstrap_paths(["pyproject.toml"]) == 0

    script = (
        'cd "$1" || exit 9; '
        'p() { touch "$1" 2>/dev/null && echo "$2=WRITABLE" || echo "$2=EROFS"; }; '
        'w() { echo x >> "$1" 2>/dev/null && echo "$2=WRITABLE" || echo "$2=EROFS"; }; '
        'w pyproject.toml BOOTSTRAP; p launcher/probe LAUNCHER; p hooks/probe HOOKS; '
        'p .claude/probe DOTCLAUDE; w Dockerfile DOCKERFILE; w scripts/run.sh RUNSH'
    )
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    _name, argv = sandbox.sandbox_argv(str(repo), str(log_dir), _IMAGE,
                                       ["/bin/sh", "-c", script, "sh", str(repo)],
                                       rw_paths=("pyproject.toml",))
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = dict(line.split("=", 1) for line in r.stdout.split())
    assert out.get("BOOTSTRAP") == "WRITABLE", r.stdout
    for key in ("LAUNCHER", "HOOKS", "DOTCLAUDE", "DOCKERFILE", "RUNSH"):
        assert out.get(key) == "EROFS", f"{key} must be read-only: {r.stdout}"
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == "x\n"
