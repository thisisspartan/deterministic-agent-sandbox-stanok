"""Wave A portion 2 (2026-10-21): guards for the launcher.kube extraction.

The agreed sequence (specs/ARCHIVE/CONTEXT-2026-10-21c.md, T3) requires for
every moved name a guard that it lives ONLY in the new module: k8s.py holds
no def and no re-export of these names (single patch home — a test stub on
kube._X intercepts every call site because the remaining k8s code reaches
them as kube._X), and no test patches or reads k8s.<moved> any more (the
patch sites were re-bound to kube together with the move).

Calibrated RED-on-bad before use: the scanners run against in-memory
mutants that re-introduce each banned shape (def in k8s.py, setattr on k8s,
assignment on k8s, direct k8s.<name> call) and against the real sources
(GREEN) — no file is written, the tree stays clean. The self-scan excludes
this file (its own mutant literals would trip the ban).
"""
import ast
import re
from pathlib import Path

from launcher import k8s, kube, netpol

TESTS_DIR = Path(__file__).resolve().parent
LAUNCHER = TESTS_DIR.parent
SELF = Path(__file__).resolve().name

# The names wave A portion 2 moved verbatim into launcher.kube.
MOVED = ["render_template", "_read_manifest", "_kubectl", "_kubectl_checked",
         "_create_manifest", "_kubectl_bin", "_namespace", "_k8s_name",
         "_cluster_env"]


def _defs(source: str) -> set[str]:
    tree = ast.parse(source)
    return {node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)}


def _banned_k8s_refs(source: str) -> list[str]:
    """Every reference that would make k8s a second home for a moved name:
    setattr(k8s, "<name>"...), k8s.<name> = ..., k8s.<name>(...) — the
    string form and the attribute form both match."""
    hits = []
    for name in MOVED:
        for pattern in (rf'setattr\(\s*k8s,\s*"{name}"',
                        rf"k8s\.{name}\b"):
            hits.extend(re.findall(pattern, source))
    return hits


def test_moved_names_live_only_in_kube() -> None:
    """Runtime identity: each moved object IS launcher.kube's, and neither
    k8s nor netpol carries the name (no facade re-export)."""
    for name in MOVED:
        impl = getattr(kube, name)
        assert impl.__module__ == "launcher.kube", name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"
        assert not hasattr(netpol, name), f"netpol re-exposes {name}"


def test_single_home_via_module_import() -> None:
    """k8s and netpol reach the moved names ONLY through the kube module
    object — the attribute lookup that makes kube the single patch home."""
    assert k8s.kube is kube
    assert netpol.kube is kube


def test_k8s_has_no_defs_of_moved_names() -> None:
    # RED calibration: the AST scanner sees a re-introduced def.
    mutant = "def _kubectl(*argv, **kw):\n    pass\n"
    assert "_kubectl" in _defs(mutant)
    # GREEN: k8s.py holds no def of any moved name.
    defs = _defs((LAUNCHER / "k8s.py").read_text(encoding="utf-8"))
    leaked = sorted(set(MOVED) & defs)
    assert leaked == [], f"k8s.py defines moved names: {leaked}"


def test_tests_ban_setattr_and_direct_refs_on_k8s_for_moved_names() -> None:
    # RED calibration: all three banned shapes are detected.
    mutant = ('    monkeypatch.setattr(k8s, "_kubectl", fake)\n'
              "    k8s._cluster_env = lambda: {}\n"
              '    k8s.render_template("x", {})\n')
    assert len(_banned_k8s_refs(mutant)) == 3
    # GREEN: no test file reaches a moved name through k8s.
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == SELF:
            continue
        hits = _banned_k8s_refs(path.read_text(encoding="utf-8"))
        assert hits == [], f"{path.name} references k8s.<moved>: {hits}"
