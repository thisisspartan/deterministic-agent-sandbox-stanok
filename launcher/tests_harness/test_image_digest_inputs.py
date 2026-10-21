"""The image-digest inputs are ONE declared list (modernization batch 2, 2026-10-08).

The image digest is computed in two places: setup.sh bakes it into the image
LABEL stanok.digest at build, gates._image_digest re-computes it in doctor.
The two must read the SAME inputs in the SAME order — and the list must
include the image's dependency lockfile: a dependency-lock change must move
the digest, otherwise a stale image passes the doctor check while carrying a
different package set than the tree declares.

N1 follow-up (2026-10-21 external review, host-side): setup.sh ordered the
glob expansion with a locale-dependent `sort` while gates.py sorts bytewise —
latent divergence, same result on today's names, different under another
locale/collation. The fix is a minimal one: the setup.sh pipeline is pinned
to LC_ALL=C, and two pins keep the two computations byte-identical:
  5  the STANOK_DIGEST line carries the LC_ALL=C pin (RED on the pre-fix
     setup.sh — plain `ls | sort` fails this assertion)
  6  the pipeline run VERBATIM on the live tree equals gates._image_digest
     under the ambient locale and, when a non-C locale is available, under
     it too (the pin's purpose: the two digest computations cannot diverge)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_image_digest_inputs.py -q
"""
import hashlib
import os
import re
import shlex
import subprocess
from pathlib import Path

from launcher import gates
from launcher.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = REPO_ROOT / "setup.sh"

LOCKFILE = "image-requirements.lock"


def _setup_sh_digest_line() -> str:
    """The literal STANOK_DIGEST assignment line in setup.sh."""
    text = SETUP_SH.read_text(encoding="utf-8")
    m = re.search(r'^STANOK_DIGEST=".*"$', text, re.M)
    assert m, "setup.sh: STANOK_DIGEST line not found"
    return m.group(0)


def _setup_sh_digest_inputs() -> list[str]:
    """The file list setup.sh feeds to `cat` for STANOK_DIGEST, normalized
    to the pattern form gates declares: quoted "$DIR/<rel>" -> <rel>;
    the $(ls "$DIR"/<glob> | sort) form and the N1-pinned
    $(LC_ALL=C ls "$DIR"/<glob> | LC_ALL=C sort) form -> <glob>."""
    line = _setup_sh_digest_line()
    m = re.search(r'STANOK_DIGEST="\$\(cat\s+(.*?)\s*\|\s*sha256sum', line)
    assert m, "setup.sh: STANOK_DIGEST computation line not found"
    inputs: list[str] = []
    toks = shlex.split(m.group(1))
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "$(ls":
            inputs.append(toks[i + 1].removeprefix("$DIR/"))
            i += 3  # skip glob, |, sort) — the loop's i += 1 completes it
        elif t == "$(LC_ALL=C":
            inputs.append(toks[i + 2].removeprefix("$DIR/"))
            # skip ls, glob, |, LC_ALL=C, sort) — the loop's i += 1 completes
            i += 5
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


def _run_digest_line(env_extra: dict) -> str:
    """Run the literal setup.sh STANOK_DIGEST line verbatim under a given
    locale environment and return the computed digest."""
    proc = subprocess.run(
        ["bash", "-c", _setup_sh_digest_line() + '\nprintf "%s" "$STANOK_DIGEST"'],
        capture_output=True, text=True,
        env=dict(os.environ, DIR=str(REPO_ROOT), **env_extra),
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _hostile_locale() -> str | None:
    """A non-C UTF-8 locale available on this host, or None."""
    proc = subprocess.run(["locale", "-a"], capture_output=True, text=True)
    names = {n.lower(): n for n in proc.stdout.split()}
    for low, name in names.items():
        if low.startswith("en_us.utf"):
            return name
    return None


def test_setup_sh_digest_line_carries_the_byte_order_pin():
    """N1 pin (2026-10-21 external review): the glob-ordering sort must be
    pinned to the C locale — gates.py orders DIGEST_INPUTS bytewise
    (sorted()), an unpinned shell `sort` follows the ambient collation.
    Calibration: RED on the pre-fix setup.sh (plain `ls | sort`);
    this assertion is the red signature of the fix."""
    line = _setup_sh_digest_line()
    assert "LC_ALL=C ls" in line and "LC_ALL=C sort" in line, (
        "setup.sh: the STANOK_DIGEST pipeline must pin LC_ALL=C on both ls "
        "and sort — an unpinned sort is locale-dependent while "
        "gates.DIGEST_INPUTS is byte-ordered")


def test_setup_sh_and_gates_digests_are_byte_identical():
    """N1 companion pin: the setup.sh pipeline run VERBATIM on the live tree
    must equal gates._image_digest — under the ambient locale and, when a
    non-C UTF-8 locale exists on the host, under it as well (proving the
    pin's purpose: the two computations cannot diverge by locale). Green on
    the pre-fix tree as well — the risk there is latent (today's stack names
    collate identically in C and en_US); this pin turns the latent risk
    into a checked invariant. Expected literals: none — both sides are
    computed, never copied."""
    expected = gates._image_digest(Config(repo_root=str(REPO_ROOT)))
    assert _run_digest_line({}) == expected
    hostile = _hostile_locale()
    if hostile is not None:
        assert _run_digest_line({"LC_ALL": hostile, "LANG": hostile}) == expected, (
            f"digest differs under {hostile}: the LC_ALL=C pin is not doing "
            "its job")
