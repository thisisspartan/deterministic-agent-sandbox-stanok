"""The image-digest inputs are ONE declared list (modernization batch 2, 2026-10-08).

The image digest is computed in two places: setup.sh bakes it into the image
LABEL stanok.digest at build, gates._image_digest re-computes it in doctor.
The two must read the SAME inputs in the SAME order — and the list must
include the image's dependency lockfile: a dependency-lock change must move
the digest, otherwise a stale image passes the doctor check while carrying a
different package set than the tree declares.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_image_digest_inputs.py -q
"""
import hashlib
import re
import shlex
import sys
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import gates  # noqa: E402
from config import Config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = REPO_ROOT / "setup.sh"

LOCKFILE = "uv.lock"


def _setup_sh_digest_inputs() -> list[str]:
    """The file list setup.sh feeds to `cat` for STANOK_DIGEST, normalized
    to the pattern form gates declares: quoted "$DIR/<rel>" -> <rel>;
    the $(ls "$DIR"/<glob> | sort) form -> <glob>."""
    text = SETUP_SH.read_text(encoding="utf-8")
    m = re.search(r'STANOK_DIGEST="\$\(cat\s+(.*?)\s*\|\s*sha256sum', text, re.S)
    assert m, "setup.sh: STANOK_DIGEST computation line not found"
    inputs: list[str] = []
    toks = shlex.split(m.group(1))
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "$(ls":
            inputs.append(toks[i + 1].removeprefix("$DIR/"))
            i += 3  # skip glob, |, sort) — the loop's i += 1 completes it
        elif t.startswith("$DIR/"):
            inputs.append(t.removeprefix("$DIR/"))
        i += 1
    return inputs


def test_gates_declares_the_digest_inputs():
    # The single declared list BOTH digest computations must follow. Absent
    # before the change -> AttributeError: the contract does not exist yet.
    inputs = list(gates.DIGEST_INPUTS)
    assert inputs[0] == "Dockerfile"
    assert "scripts/run.sh" in inputs


def test_digest_inputs_include_the_dependency_lockfile():
    assert LOCKFILE in list(gates.DIGEST_INPUTS)


def test_setup_sh_and_gates_read_the_same_inputs_in_the_same_order():
    assert _setup_sh_digest_inputs() == list(gates.DIGEST_INPUTS)


def test_image_digest_follows_the_declared_order(tmp_path):
    # Distinct content per input: the digest must equal sha256 over the
    # concatenation in the declared order (glob entries resolved sorted).
    bodies = {
        "Dockerfile": b"D\n",
        "scripts/run.sh": b"R\n",
        "scripts/stacks/b.toml": b"Z2\n",
        "scripts/stacks/a.toml": b"Z1\n",
        LOCKFILE: b"L\n",
    }
    for rel, body in bodies.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    expected = hashlib.sha256(b"D\nR\nZ1\nZ2\nL\n").hexdigest()
    assert gates._image_digest(Config(repo_root=str(tmp_path))) == expected
