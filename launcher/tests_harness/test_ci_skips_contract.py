"""Pair test for launcher/ci_skips.py (nodeid skip-contract, 2026-10-20).

Contract source: specs/SPEC-CI-MINIMAL-2026-10-13.md (nodeid revision
2026-10-20, operator approval 2026-10-20): the CI skip contract is the exact
SET of skipped-test nodeids "<path>.py::<test-name>", position-independent —
editing a test file must no longer redden CI by moving skip statements.

Expected literals below are host-authored (this file + the SPEC), derived
from the fixture trees written here — contract assertions, not
characterization.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_ci_skips_contract.py -q
"""
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from launcher import ci_skips

REPO_ROOT = Path(__file__).resolve().parents[2]


def _junit(path, cases):
    """Write a synthetic junit-xml: cases = list of (kind, file|None,
    classname|None, name). kind in {"pass", "skip", "fail"}."""
    ts = ET.Element("testsuite", tests=str(len(cases)))
    for kind, file, cls, name in cases:
        attrs = {"name": name, "classname": cls or "", "time": "0.01"}
        if file:
            attrs["file"] = file
        tc = ET.SubElement(ts, "testcase", **attrs)
        if kind == "skip":
            ET.SubElement(tc, "skipped", type="pytest.skip", message="guard")
        elif kind == "fail":
            ET.SubElement(tc, "failure", message="boom")
    ET.ElementTree(ts).write(str(path), encoding="utf-8")


def _tree(tmp_path, files):
    """Materialize a fake repo tree so classname derivation can resolve."""
    for f in files:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")


def test_extract_nodeids_position_independent(tmp_path, monkeypatch):
    # Fixture tree + fixture junit-xml; expected literals hand-written
    # (contract provenance): only skipped testcases appear, sorted, in
    # "<path>.py::<name>" form.
    _tree(tmp_path, ["launcher/tests_harness/test_a.py",
                     "launcher/tests_harness/test_b.py",
                     "launcher/tests_harness/test_doctor.py"])
    xml = tmp_path / "skips.xml"
    _junit(xml, [
        ("pass", None, "launcher.tests_harness.test_a", "test_ok"),
        ("skip", None, "launcher.tests_harness.test_doctor", "test_zeta"),
        ("skip", "launcher/tests_harness/test_b.py",
         "launcher.tests_harness.test_b", "test_alpha"),
        ("fail", None, "launcher.tests_harness.test_a", "test_fails"),
        ("skip", None, "launcher.tests_harness.test_a", "test_alpha"),
    ])
    monkeypatch.chdir(tmp_path)
    assert ci_skips.extract(str(xml)) == [
        "launcher/tests_harness/test_a.py::test_alpha",
        "launcher/tests_harness/test_b.py::test_alpha",
        "launcher/tests_harness/test_doctor.py::test_zeta",
    ]
    # A passed or failed test never enters the set; line numbers are absent
    # from the output entirely (the position-drift failure mode is gone).
    for nid in ci_skips.extract(str(xml)):
        assert "\n" not in nid and ":" not in nid.split("::", 1)[0]


def test_class_based_skip_resolves_to_module_file(tmp_path, monkeypatch):
    # junit-xml gives classname = <module>.<Class> and name = the method:
    # the module path is the longest dot-prefix backed by a real file, the
    # rest is the class chain — a class component must never become a path.
    _tree(tmp_path, ["pkg/test_cls.py"])
    xml = tmp_path / "skips.xml"
    _junit(xml, [("skip", None, "pkg.test_cls.TestCls", "test_method")])
    monkeypatch.chdir(tmp_path)
    assert ci_skips.extract(str(xml)) == ["pkg/test_cls.py::TestCls::test_method"]


def test_unresolvable_fails_closed(tmp_path, monkeypatch):
    # No classname/file and a classname that matches no real file: the
    # nodeid cannot be derived — the contract must surface it, not encode a
    # plausible-but-wrong id or drop the skip silently.
    xml = tmp_path / "skips.xml"
    _junit(xml, [
        ("skip", None, None, "test_ghost"),
        ("skip", None, "pkg.test_missing", "test_x"),
        ("skip", None, "pkg.test_cls.TestNotAClass", "test_y"),
    ])
    _tree(tmp_path, ["pkg/other.py"])
    monkeypatch.chdir(tmp_path)
    assert ci_skips.extract(str(xml)) == [
        "<unresolved>::test_ghost",
        "<unresolved>::test_x",
        "<unresolved>::test_y",
    ]


def _parent_repo_state():
    parent = REPO_ROOT.parent
    rc = subprocess.run(["git", "-C", str(parent), "rev-parse", "--git-dir"],
                        capture_output=True, text=True).returncode
    if rc != 0:
        return "absent"
    gm = parent / ".gitmodules"
    if not gm.is_file() or "stanok" not in gm.read_text(encoding="utf-8"):
        return "not-parent"
    return "present"


def test_published_skip_list_is_nodeid_contract():
    # The published contract file must be exactly 11 entries in nodeid form
    # (the count stays the secondary check per SPEC-CI-MINIMAL; 10 -> 11 on
    # 2026-10-22 per SPEC-DOCTOR-CLI-VERSION-2026-10-22). Guarded in the
    # published-parent layout only — outside it, skip, never vacuous.
    state = _parent_repo_state()
    if state != "present":
        pytest.skip(f"parent layout state {state!r} — the contract file lives "
                    "in the published parent only")
    f = REPO_ROOT.parent / ".github" / "ci-expected-skips.txt"
    if not f.is_file():
        pytest.fail("published parent has no .github/ci-expected-skips.txt")
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    assert len(lines) == 11, f"expected exactly 11 contract entries, got {len(lines)}"
    assert len(set(lines)) == 11, "contract entries must be unique"
    for ln in lines:
        path, _, name = ln.partition("::")
        assert path.endswith(".py") and name, \
            f"contract entry is not a nodeid '<path>.py::<name>': {ln!r}"
