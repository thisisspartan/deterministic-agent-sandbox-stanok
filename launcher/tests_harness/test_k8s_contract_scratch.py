"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §6) — the host contract recompute
over the PATCHED SCRATCH tree.

In k8s mode the live tree is never touched during the run: the Pod works on
a transported copy. The tree the verdict was computed against is therefore
`clean tree + changes.patch` — the host recomputes the protected-files
manifest against a scratch copy (extract tree + git apply patch) using the
SAME verify._compare_manifests as the Docker path (the two cannot drift).
Tests:
  1  a patch that adds an UNDECLARED src/ file -> UNDECLARED violation
     (the CC-222 hole, caught host-side)
  2  a patch that adds only the declared paths -> clean
  3  a patch that MODIFIES a pre-existing protected test -> MODIFIED
     violation
  4  (wave C, operator 2026-10-20: same failure class as the numstat
     mkdtemp case — variant 2) apply_patch_scratch: a tempfile.mkdtemp
     OSError must reach the existing PATCH-APPLY channel (caller maps
     RuntimeError, k8s.py), never escape as a raw OSError (host_launch_k8s
     has no except Exception — the run would die with no verdict).
     Characterization: the channel mapping is pinned end-to-end in
     test_k8s_wiring.py (real apply, published CONTRACT-FAIL).
  5  (wave C) a `git apply` failure in the scratch must not leak the
     scratch temp dir (the variant-2 cleanup discipline; the
     `git apply failed (rc=...)` literal is characterization — its only
     source is k8s.py apply_patch_scratch itself).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_contract_scratch.py -q
"""
import os
import subprocess
import tempfile

from launcher import k8s, verify
from launcher.config import Config


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "scripts").mkdir()
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    (repo / "tests" / "t_test.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                    capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "base")
    return repo


def _cfg(repo, tmp_path):
    return Config(repo_root=str(repo), log_dir=str(tmp_path / "logs"))


def _new_file_patch(path, body):
    lines = body.splitlines()
    n = len(lines)
    return (f"diff --git a/{path} b/{path}\n"
            f"new file mode 100644\n"
            f"--- /dev/null\n"
            f"+++ b/{path}\n"
            f"@@ -0,0 +1,{n} @@\n"
            + "".join(f"+{ln}\n" for ln in lines))


def test_undeclared_src_file_is_a_violation(tmp_path):
    repo = _repo(tmp_path)
    cfg = _cfg(repo, tmp_path)
    before = verify.contract_snapshot(cfg)
    patch = _new_file_patch("src/helper.py", "def twice(n):\n    return 2 * n")
    scratch = k8s.apply_patch_scratch(k8s.pack_tree(str(repo)), patch)
    v = k8s.scratch_contract_violations(
        cfg, before, scratch, ["src/k8s_contract.py", "tests/k8s_contract_test.py"])
    assert any("UNDECLARED: src/helper.py" in x for x in v)


def test_declared_paths_only_is_clean(tmp_path):
    repo = _repo(tmp_path)
    cfg = _cfg(repo, tmp_path)
    before = verify.contract_snapshot(cfg)
    patch = (_new_file_patch("src/k8s_contract.py", "from doubling import twice")
             + _new_file_patch("tests/k8s_contract_test.py", "def test_x(): pass"))
    scratch = k8s.apply_patch_scratch(k8s.pack_tree(str(repo)), patch)
    v = k8s.scratch_contract_violations(
        cfg, before, scratch, ["src/k8s_contract.py", "tests/k8s_contract_test.py"])
    assert v == []


def test_modified_protected_test_is_a_violation(tmp_path):
    repo = _repo(tmp_path)
    cfg = _cfg(repo, tmp_path)
    before = verify.contract_snapshot(cfg)
    patch = ("diff --git a/tests/t_test.py b/tests/t_test.py\n"
             "index 1111111..2222222 100644\n"
             "--- a/tests/t_test.py\n"
             "+++ b/tests/t_test.py\n"
             "@@ -1 +1 @@\n"
             "-def test_ok(): pass\n"
             "+def test_ok(): pass  # tampered\n")
    scratch = k8s.apply_patch_scratch(k8s.pack_tree(str(repo)), patch)
    v = k8s.scratch_contract_violations(cfg, before, scratch, [])
    assert any("MODIFIED: tests/t_test.py" in x for x in v)


# --- wave C (operator 2026-10-20): scratch setup failure class (tests 4/5) ---

def test_scratch_mkdtemp_oserror_reaches_the_runtime_error_channel(monkeypatch):
    # Wave C item (apply_patch_scratch:296): a tempfile.mkdtemp failure must
    # not escape as a raw OSError — host_launch_k8s catches only
    # RuntimeError at the call site (k8s.py, "PATCH-APPLY:" mapping) and has
    # no except Exception, so a raw OSError kills the run without any
    # published verdict. The channel type (RuntimeError) is pinned
    # end-to-end in test_k8s_wiring.test_scratch_setup_failure_publishes
    # _contract_fail; here only the type — the message wording is not a
    # contract.
    def boom(*a, **k):
        raise OSError("mkdtemp: no space left on device")
    monkeypatch.setattr(k8s.tempfile, "mkdtemp", boom)
    try:
        k8s.apply_patch_scratch("ignored-blob", "")
        raise AssertionError("apply_patch_scratch returned despite mkdtemp failure")
    except RuntimeError:
        pass  # correct: mapped, never a raw OSError (OSError would escape)


def test_scratch_git_apply_failure_does_not_leak_temp_dir(tmp_path, monkeypatch):
    # A scratch dir created before a failed `git apply` must be removed —
    # variant-2 cleanup discipline applied to the existing RuntimeError path
    # (it raised the right type but left the dir in $TMPDIR). The
    # "git apply failed" literal is characterization (source: k8s.py).
    repo = _repo(tmp_path)
    blob = k8s.pack_tree(str(repo))
    created = []
    real_mkdtemp = tempfile.mkdtemp  # bind BEFORE patching: k8s.tempfile is
    # this same module — calling tempfile.mkdtemp inside the spy self-recurses.

    def spy(*a, **k):
        d = real_mkdtemp(*a, **k)
        created.append(d)
        return d
    monkeypatch.setattr(k8s.tempfile, "mkdtemp", spy)
    try:
        k8s.apply_patch_scratch(blob, "this is not a diff at all\n")
        raise AssertionError("apply_patch_scratch returned despite bad patch")
    except RuntimeError as e:
        assert "git apply failed" in str(e)
    assert created, "spy never recorded a scratch dir"
    assert all(not os.path.isdir(d) for d in created), \
        f"scratch dir leaked: {[d for d in created if os.path.isdir(d)]}"
