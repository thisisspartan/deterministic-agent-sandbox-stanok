"""CC-150 — bootstrap gate for top-level paths (hermetic).

A NEW top-level file (e.g. `pyproject.toml`) has no existing ancestor to carve
out (declared_carveout -> None), so it cannot be declared `impl:`/`edit:`. The
`bootstrap:` declaration kind creates it, gated by:

  - the path is in the audited per-stack `bootstrap_paths` set
    (scripts/stacks/*.toml) — fail-closed to the EMPTY set when no manifest
    parses (bootstrap is a NEW capability; it never silently widens);
  - the path does not already exist (bootstrap creates a NEW file);
  - the path cannot escape the repo (relative, no `..`, no symlink out);
  - `scripts/run.sh` is absent OR declared in the ticket (bootstrap is for a
    NEW project whose entrypoint does not yet exist / is being created).

When bootstrap is active the repo ROOT is mounted rw and `.git` + every
pre-existing protected file (tests/**, run.sh) are re-bound :ro, so "tests are
immutable" is preserved at the filesystem layer.

Cases:
  1  audited path + run.sh absent            -> allowed
  2  path NOT in audited set                 -> rejected
  3  run.sh present, not declared            -> rejected
  4  run.sh present + declared (edit:)       -> allowed
  5  audited path already exists             -> rejected
  6  `..` escape                             -> rejected
  7  absolute path                           -> rejected
  8  no manifest (fail-closed)               -> rejected
  9  host_ro_paths with repo-root carve-out  -> re-binds all protected files
  10 sandbox_argv repo_rw=True               -> repo root mounted :rw

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_bootstrap_gate.py -q
"""
import os
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


# --- 4: run.sh present + declared (edit:) -> allowed -------------------------

def test_bootstrap_runsh_declared(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"scripts/run.sh": "#!/bin/sh\n"},
                manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    declared, edit, reset, bootstrap = stanok.parse_ticket_header(
        "bootstrap: pyproject.toml\nedit: scripts/run.sh\n")
    assert bootstrap == ["pyproject.toml"]
    assert edit == ["scripts/run.sh"]
    assert declared == ["pyproject.toml", "scripts/run.sh"]


# --- 5: audited path already exists -> rejected -----------------------------

def test_bootstrap_path_exists_rejected(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"pyproject.toml": "[tool]\n"},
                manifest=PY_BOOTSTRAP_MANIFEST)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    with pytest.raises(ValueError):
        stanok.parse_ticket_header("bootstrap: pyproject.toml\n")


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


# --- 9: host_ro_paths with repo-root carve-out re-binds all protected files --

def test_host_ro_paths_repo_root_carveout(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {
        "tests/foo_test.py": "def test_ok():\n    assert True\n",
        "scripts/run.sh": "#!/bin/sh\n",
    })
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    # carve-out "" = the repo root (bootstrap active): every protected file is
    # within it and must be re-bound :ro.
    ro = stanok.host_ro_paths([], ("",))
    assert set(ro) == {"tests/foo_test.py", "scripts/run.sh"}


# --- 10: sandbox_argv repo_rw=True mounts the repo root :rw ------------------

def test_sandbox_argv_repo_rw(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    log_dir = tmp_path / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    _name, argv = sandbox.sandbox_argv(str(repo), str(log_dir), "img",
                                       ["cmd"], repo_rw=True)
    assert f"{repo}:{repo}:rw" in argv
    # and the default stays read-only
    _name2, argv2 = sandbox.sandbox_argv(str(repo), str(log_dir), "img",
                                         ["cmd"])
    assert f"{repo}:{repo}:ro" in argv2
    assert f"{repo}:{repo}:rw" not in argv2
