"""Contract for the lint gates (T1/T2, 2026-10-20 — operator-ordered ruff/mypy wave).

The gate IS its config file: ruff.toml (whole tree, the documented
tests_harness per-file-ignores) and mypy.ini (launcher production code only).
This file pins only what the configs' existence and the real tool runs prove:

  G1  both gate configs exist — a deleted config silently changes what a
      gate checks (ruff without a config falls back to its defaults; mypy
      without a config checks nothing and exits 0), so absence must redden,
      not fall back.
  G2  where the tools are on PATH (host, or CI with the pinned
      lint-requirements.lock installed — the harness job installs it), each
      gate runs green against the real tree; a non-zero rc reproduces the
      tool output.

Skip-guards follow the _NO_JQ pattern (SPEC-CI-MINIMAL): on a bare checkout
without the tools the probe is a refusal with a reason. In the CI harness job
the tools ARE installed, so both probes RUN there and add nothing to the
skip set — if the install step is ever dropped, these probes flip to skips
and the published skip-set contract reddens. That is the point: the install
step and the gate are pinned to each other from both sides.

Versions: ruff==0.15.20 / mypy==2.2.0 are pinned in lint-requirements.lock
(the source of these literals); the host toolchain must match, and a
host/CI divergence surfaces as different gate output on one side.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_lint_gates.py -q
"""
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT

_NO_RUFF = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason="ruff not on PATH (bare environment) — lint gate not applicable",
)
_NO_MYPY = pytest.mark.skipif(
    shutil.which("mypy") is None,
    reason="mypy not on PATH (bare environment) — lint gate not applicable",
)


def test_G1_gate_configs_exist():
    assert (REPO_ROOT / "ruff.toml").is_file(), (
        "ruff.toml missing — without it `ruff check .` falls back to ruff's "
        "default rule selection (the scope the T1 wave defined)")
    assert (REPO_ROOT / "mypy.ini").is_file(), (
        "mypy.ini missing — without it `mypy` with no arguments checks "
        "nothing and exits 0 (a vacuously green gate)")


@_NO_RUFF
def test_G2_ruff_gate_green():
    # --no-cache: the gate must not trust a cached verdict from an earlier tree
    p = subprocess.run(["ruff", "check", "--no-cache", "."], cwd=REPO_ROOT,
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr


@_NO_MYPY
def test_G2_mypy_gate_green():
    # cwd=REPO_ROOT: mypy.ini's `files = launcher` is cwd-relative, and the
    # cache lands in REPO_ROOT/.mypy_cache (mypy writes a `*` .gitignore
    # into its own cache dir — verified: the tree stays clean without a
    # project gitignore entry).
    p = subprocess.run(["mypy", "--config-file", "mypy.ini"], cwd=REPO_ROOT,
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout + p.stderr
