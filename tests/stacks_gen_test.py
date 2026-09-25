"""Generator contract tests for the single-stack manifest registry (D2).

The STACK REGISTRY in scripts/run.sh is generated from one TOML manifest
per stack in scripts/stacks/ by scripts/gen_stacks.sh. These tests pin the
generator contract:

- `--check` exits 0 on the committed state (real repo);
- `--check` exits 1 after tampering with a copy of a manifest (temp tree);
- the generated STACKS block equals the expected 3 registry lines (as a
  set of lines; order per the generator's manifest-filename sort rule);
- domains.json parses as JSON and equals the sorted union of all domains;
- runtime.list has one line per runtime entry, in manifest order.

All generation happens in a temp tree (tmp_path); the real scripts/ tree
is only ever read.
"""

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
GEN = SCRIPTS / "gen_stacks.sh"

# The 3 registry lines that must be preserved byte-identically (order in
# this dict is irrelevant — the generator emits manifest sort order).
EXPECTED_LINES = {
    "js|*.test.js|[A-Za-z0-9_-]+\\.test\\.js|node --test --test-force-exit|node|node --version",
    "py|*_test.py|[A-Za-z0-9_-]+_test\\.py|env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider -o pythonpath=src|env PYTHONDONTWRITEBYTECODE=1 python3|env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --version",
    "jq|*.json|[A-Za-z0-9_-]+\\.json|jq empty|jq empty|command -v jq",
}

# Manifest filename sort order: jq.toml, js.toml, py.toml.
EXPECTED_ORDER = ["jq", "js", "py"]

EXPECTED_DOMAINS = [
    "files.pythonhosted.org",
    "pypi.org",
    "registry.npmjs.org",
]

EXPECTED_RUNTIME = [
    "jq",
    "node v22.22.3 (nodejs.org tarball, sha256-pinned in Dockerfile)",
    "python3",
    "python3-venv",
    "uv (pinned 0.5.24)",
    "pytest",
]


def _copy_scripts(tmp_path: Path) -> Path:
    """Copy the real scripts/ tree into a temp tree and return its root."""
    tree = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, tree)
    return tree


def _generate(tree: Path) -> None:
    """Run the generator (no args) inside a temp scripts/ tree."""
    r = subprocess.run(
        ["bash", str(tree / "gen_stacks.sh")],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"generator failed: {r.stderr}"


def test_check_committed_state():
    """`--check` exits 0 on the committed state (run against the real repo)."""
    assert GEN.is_file(), "scripts/gen_stacks.sh is missing"
    r = subprocess.run(
        ["bash", str(GEN), "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"--check failed: {r.stderr}"


def test_check_detects_tampered_manifest(tmp_path):
    """`--check` exits 1 after tampering with a copy of a manifest."""
    tree = _copy_scripts(tmp_path)
    manifest = tree / "stacks" / "js.toml"
    text = manifest.read_text()
    assert 'ext = "js"' in text
    manifest.write_text(text.replace('ext = "js"', 'ext = "js2"'))
    r = subprocess.run(
        ["bash", str(tree / "gen_stacks.sh"), "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1, f"expected rc=1, got {r.returncode}: {r.stderr}"
    assert "stacks.generated.sh" in r.stderr, (
        f"drift message must name the drifted file: {r.stderr}"
    )


def test_generated_stacks_block(tmp_path):
    """The generated STACKS block equals the expected 3 lines (set + order)."""
    tree = _copy_scripts(tmp_path)
    _generate(tree)
    content = (tree / "stacks.generated.sh").read_text()
    assert content.startswith("STACKS='"), f"unexpected head: {content[:40]!r}"
    assert content.endswith("'\n"), f"unexpected tail: {content[-40:]!r}"
    body = content[len("STACKS='") : -2]
    lines = body.split("\n")
    assert set(lines) == EXPECTED_LINES, (
        f"registry lines drifted:\n got: {lines}\n want: {sorted(EXPECTED_LINES)}"
    )
    assert [line.split("|", 1)[0] for line in lines] == EXPECTED_ORDER, (
        f"line order must follow manifest sort order: {lines}"
    )


def test_generated_domains_json(tmp_path):
    """domains.json parses as JSON and equals the sorted union of domains."""
    tree = _copy_scripts(tmp_path)
    _generate(tree)
    raw = (tree / "stacks.generated" / "domains.json").read_text()
    doms = json.loads(raw)
    assert doms == EXPECTED_DOMAINS, f"domains drifted: {doms}"


def test_generated_runtime_list(tmp_path):
    """runtime.list has one line per runtime entry, in manifest order."""
    tree = _copy_scripts(tmp_path)
    _generate(tree)
    lines = (tree / "stacks.generated" / "runtime.list").read_text().splitlines()
    assert lines == EXPECTED_RUNTIME, f"runtime.list drifted: {lines}"
