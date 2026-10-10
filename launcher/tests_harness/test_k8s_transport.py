"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §4, O4) — the tree transport.

The Pod has no repo: the host ships the tree as `git archive HEAD | gzip |
base64` through a ConfigMap (the SPEC-sanctioned tarball fallback; the full
git bundle is 1.3MB > the 800KB ConfigMap threshold — the measured decision
of 2026-10-10). Tests:
  1  pack_tree/unpack_tree round-trip: the Pod reconstructs the tracked tree
     (no .git — the Pod re-inits its own git for the patch)
  2  the packed blob is valid base64 and the size guard refuses a blob over
     the ConfigMap threshold (fail-closed before any kubectl call)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_transport.py -q
"""
import base64
import subprocess

from launcher import k8s


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("X = 1\n", encoding="utf-8")
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True,
                                    capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "base")
    return repo


def test_pack_unpack_roundtrip(tmp_path):
    repo = _make_repo(tmp_path)
    blob = k8s.pack_tree(str(repo))
    dest = tmp_path / "out"
    dest.mkdir()
    k8s.unpack_tree(blob, str(dest))
    assert (dest / "src" / "a.py").read_text(encoding="utf-8") == "X = 1\n"
    # The Pod re-inits its own git: the transport carries the tree, not .git.
    assert not (dest / ".git").exists()


def test_pack_is_compact_base64_and_guarded(tmp_path):
    repo = _make_repo(tmp_path)
    blob = k8s.pack_tree(str(repo))
    base64.b64decode(blob)  # must be valid base64 (ConfigMap value)
    assert len(blob) < 100_000  # a small repo packs small (gzip works)
    assert k8s.transport_ok(blob) is True
    assert k8s.transport_ok("x" * (k8s.TRANSPORT_MAX_B64 + 1)) is False
