"""C3 (review 2026-10-17) — the fresh Job Pod's own apply guard, executed for real.

test_k8s_manifests.py pins the guard's TEXT in fresh-job.yaml.tmpl; this file
runs the REAL Pod script — extracted from the template, not a hand copy — under
bash against a synthetic tree/patch fixture (the same transport format the host
packs: git archive HEAD | gzip | base64, k8s.py pack_tree):
  1  a failed git apply exits with FRESH_APPLY_FAIL_RC BEFORE any test runs:
     the run.sh stub's marker is absent, the failure line is on stderr
  2  a valid patch applies, the suite runs, the exit rc is the suite's
  3  an empty changes.patch skips the apply entirely (the `-s` guard)
  4  FRESH_APPLY_FAIL_RC is disjoint from every run.sh/runner code, so the
     host's exit-20 -> EXEC_ERROR mapping (test_k8s_infra_cause.py item 7)
     can never collide with a test result

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_fresh_apply_guard.py -q
"""
import base64
import gzip
import os
import subprocess
import textwrap
from pathlib import Path

from launcher import k8s

K8S_DIR = Path(__file__).resolve().parents[2] / "k8s"

BAD_PATCH = (
    "--- a/ghost.txt\n"
    "+++ b/ghost.txt\n"
    "@@ -1,1 +1,1 @@\n"
    "-old\n"
    "+new\n"
)

GOOD_PATCH = (
    "diff --git a/applied.txt b/applied.txt\n"
    "new file mode 100644\n"
    "index 0000000..f8e3fd7\n"
    "--- /dev/null\n"
    "+++ b/applied.txt\n"
    "@@ -0,0 +1 @@\n"
    "+applied\n"
)


def _pod_script() -> str:
    """The real Pod script from fresh-job.yaml.tmpl: the args block between
    `set -u` and `exit "$test_rc"`, dedented, {{APPLY_FAIL_RC}} rendered the
    way k8s.py renders it."""
    tmpl = (K8S_DIR / "fresh-job.yaml.tmpl").read_text(encoding="utf-8")
    lines = tmpl.splitlines()
    i0 = next(i for i, l in enumerate(lines) if l.strip() == "set -u")
    i1 = next(i for i, l in enumerate(lines) if l.strip() == 'exit "$test_rc"')
    script = textwrap.dedent("\n".join(lines[i0:i1 + 1]))
    # wiring: this test runs the template's guard, not a copy of it
    assert "git apply /stanok/patch/changes.patch || {" in script
    assert "exit {{APPLY_FAIL_RC}}" in script
    return script.replace("{{APPLY_FAIL_RC}}", str(k8s.FRESH_APPLY_FAIL_RC))


def _relocate(script: str, root: Path) -> str:
    """Move the Pod's mount points into the tmp dir (host run)."""
    return (script
            .replace("/stanok-work", str(root / "stanok-work"))
            .replace("/stanok/transport", str(root / "stanok-transport"))
            .replace("/stanok/patch", str(root / "stanok-patch")))


def _fixture_tree(tmp_path: Path) -> bytes:
    """A synthetic project tree, archived the way pack_tree does it."""
    repo = tmp_path / "src-tree"
    (repo / "tests").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "tests" / "t_test.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "list" ]; then echo "tests/t_test.py"; exit 0; fi\n'
        'if [ "$1" = "test" ] && [ "$2" = "--all" ]; then touch "$MARKER"; exit 0; fi\n'
        "exit 3\n", encoding="utf-8")
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["-c", "user.email=fixture@local", "-c", "user.name=fixture",
                          "commit", "-qm", "fixture"], check=True)
    archive = subprocess.run(git + ["archive", "HEAD"], capture_output=True,
                             check=True).stdout
    return gzip.compress(archive)


def _run_pod(tmp_path: Path, patch_text: str):
    root = tmp_path
    (root / "stanok-transport").mkdir()
    (root / "stanok-transport" / "tree.tar.gz.b64").write_bytes(
        base64.b64encode(_fixture_tree(tmp_path)))
    (root / "stanok-patch").mkdir()
    (root / "stanok-patch" / "changes.patch").write_text(patch_text,
                                                          encoding="utf-8")
    marker = root / "ran-tests"
    proc = subprocess.run(
        ["bash", "-c", _relocate(_pod_script(), root)],
        capture_output=True, text=True,
        env=dict(os.environ, MARKER=str(marker)))
    return proc, marker


def test_apply_failure_exits_before_tests(tmp_path):
    proc, marker = _run_pod(tmp_path, BAD_PATCH)
    assert proc.returncode == k8s.FRESH_APPLY_FAIL_RC
    assert not marker.exists()  # no test ran on the unpatched tree
    assert "FRESH: git apply" in proc.stderr


def test_valid_patch_applies_and_suite_runs(tmp_path):
    proc, marker = _run_pod(tmp_path, GOOD_PATCH)
    assert proc.returncode == 0
    assert marker.exists()
    assert (tmp_path / "stanok-work" / "work" / "applied.txt").exists()


def test_empty_patch_skips_apply(tmp_path):
    proc, marker = _run_pod(tmp_path, "")
    assert proc.returncode == 0
    assert marker.exists()


def test_apply_fail_rc_disjoint_from_run_codes():
    # run.sh W12 codes and every runner's codes (pytest 0-5, node 0/1, jq 0/5)
    assert k8s.FRESH_APPLY_FAIL_RC not in {0, 1, 2, 3, 4, 5, 6, 7, 124}
