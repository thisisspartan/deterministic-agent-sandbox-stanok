"""Contract for the shell gate (Q2-shellcheck, 2026-10-21 external review).

The shell layer the launcher itself runs through — setup.sh (build/setup),
launch.sh (supervisor entrypoint), scripts/run.sh (the test entrypoint and
W12 contract) — was linted by nothing: ruff/mypy cover the python layer,
run.sh is contract-tested for BEHAVIOUR but never statically. This gate
runs the real tool (shellcheck-py==0.11.0.1 — the version pinned in
lint-requirements.lock, the source of this literal) over the three scripts.

Deviations are pinned with in-place `# shellcheck disable=` comments and
their justifications at the finding sites (word splitting feeding cat in
setup.sh; unquoted pattern-match RHS in run.sh; ASCII-only case folding in
run.sh) — a disable there is a claim that the flagged construct is the
mechanism, and the justification next to it is what a future reader checks.

Skip-guard follows the _NO_JQ/_NO_RUFF pattern: on a bare checkout without
the tool the probe is a refusal with a reason; in the CI harness job the
tool IS installed (the job pip-installs lint-requirements.lock, the PATH
farm lets it through), so the probe RUNS there and adds nothing to the
published skip set — dropping the install step flips these probes to skips
and reddens the skip-set contract, the same two-sided pin as the lint gates.

Calibration signature: on the pre-fix scripts (plain `$(ls | sort)` in
setup.sh, `export x="$(...)"` in launch.sh, no disable directives) the
gate ran RED — SC2046/SC2012, SC2155, SC2053/SC2018/SC2019; the one
genuine defect (SC2155, command-substitution failure masked by export) was
FIXED in launch.sh, the rest are declared intentional at their sites.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_shellcheck_gates.py -q
"""
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT

_NO_SHELLCHECK = pytest.mark.skipif(
    shutil.which("shellcheck") is None,
    reason="shellcheck not on PATH (bare environment) — shell gate not applicable",
)

_SHELL_SCRIPTS = ("setup.sh", "launch.sh", "scripts/run.sh")


@_NO_SHELLCHECK
@pytest.mark.parametrize("script", _SHELL_SCRIPTS)
def test_S2_shellcheck_gate_green(script):
    p = subprocess.run(["shellcheck", script], cwd=REPO_ROOT,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
