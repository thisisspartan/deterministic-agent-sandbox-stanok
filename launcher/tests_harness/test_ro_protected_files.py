"""The protected-file manifest: ONE source (CC-136/CC-206, runtime-agnostic).

`_protected_files` is the single list — tests/**, scripts/run.sh (when
present), scripts/stacks/*.toml — and `_tests_manifest` (the contract_lock
manifest) is the SAME rule, not a second policy list.

The mount mechanics were removed with the Docker path (CC-258); their
invariants are pinned on the k8s path: read-only roots and tmp/home
alignment by test_k8s_manifests.py; protected-file detection and the
hard-link residual closure (CC-206: detection, not prevention) by the
contract-recompute tests (test_stage3_host_snapshot / test_stage3_tests_tree /
test_stage3_src_tree / test_stage3_host_recompute / test_scenarios_verdict).
What is tested here is the runtime-agnostic core: the protected list itself.

Tests:
  1  the protected list == tests/** + scripts/run.sh + scripts/stacks/*.toml,
     and _tests_manifest == the same set
  2  bootstrap: an absent scripts/run.sh is NOT protected (it may be
     created); the stacks manifests are protected anyway

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_ro_protected_files.py -q
"""
from launcher import verify
from launcher.config import Config

from conftest import repo, write  # noqa: F401


# --- the protected list: one source ---------------------------------------------

def test_protected_files_are_tests_runsh_and_stacks(repo):
    write(repo / "tests" / "a_test.py", "def test_a():\n    assert 1\n")
    write(repo / "tests" / "sub" / "b_test.py", "def test_b():\n    assert 1\n")
    write(repo / "tests" / "__pycache__" / "a_test.cpython-313.pyc", "junk")
    cfg = Config(repo_root=str(repo))
    protected = verify._protected_files(cfg)
    # B1 (PLAN-AUDIT-2026-10-08): the stacks manifests are contract files too
    # (run.sh derives its registry from them) — see test_stacks_protected.py.
    assert set(protected) == {"tests/a_test.py", "tests/sub/b_test.py",
                              "scripts/run.sh",
                              "scripts/stacks/jq.toml", "scripts/stacks/js.toml",
                              "scripts/stacks/py.toml"}
    # The manifest and the protected list are the same rule, not two policy
    # lists.
    assert set(verify._tests_manifest(cfg)) == set(protected)


def test_protected_list_without_a_runsh(repo):
    # Bootstrap: a missing scripts/run.sh is not protected (it may be created).
    # The stacks manifests are pre-existing infrastructure — protected anyway.
    write(repo / "tests" / "a_test.py", "def test_a():\n    assert 1\n")
    (repo / "scripts" / "run.sh").unlink()
    assert verify._protected_files(Config(repo_root=str(repo))) == [
        "tests/a_test.py",
        "scripts/stacks/jq.toml", "scripts/stacks/js.toml",
        "scripts/stacks/py.toml"]
