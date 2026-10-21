"""Wave A portion 5 (2026-10-21): guards for the launcher.peaks extraction.

The agreed sequence (specs/ARCHIVE/CONTEXT-2026-10-21c.md, T3) requires for
every moved name a guard that it lives ONLY in the new module: k8s.py holds
no def, no constant and no re-export of the resource-sampling names, and no
test patches or reads k8s.<moved> any more (the patch sites were re-bound to
peaks together with the move — single home: k8s construction sites reach the
sampler as peaks._ResourceSampler, and the class resolves its helpers through
this module's globals, so a test stub on a name here intercepts every call
site). The setattr's on the SHARED module object (kube._kubectl /
kube._kubectl_checked — the kubectl wrappers) stay: kube is the same module
object in every importer, patching it intercepts peaks calls regardless of
importer (portion-2 precedent).

Calibrated RED-on-bad before use: the scanners run against in-memory
mutants that re-introduce each banned shape (def in k8s.py, module-level
constant assignment in k8s.py, setattr on k8s, assignment on k8s, direct
k8s.<name> call) and against the real sources (GREEN) — no file is written,
the tree stays clean. The self-scan excludes this file (its own mutant
literals would trip the ban).
"""
import ast
import re
from pathlib import Path

from launcher import k8s, peaks

TESTS_DIR = Path(__file__).resolve().parent
LAUNCHER = TESTS_DIR.parent
SELF = Path(__file__).resolve().name

# The names wave A portion 5 moved verbatim into launcher.peaks: the
# resource-sampling cluster and the interval constant its signature resolves
# through module globals.
MOVED = ["_node_of_pod", "_kubelet_stats", "_peak_from_stats",
         "_ResourceSampler"]
CONSTANTS = ["SAMPLE_INTERVAL_S"]


def _defs(source: str) -> set[str]:
    tree = ast.parse(source)
    return {node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef
                         | ast.ClassDef)}


def _module_constants(source: str) -> set[str]:
    tree = ast.parse(source)
    return {t.id for node in tree.body if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name)}


def _banned_k8s_refs(source: str) -> list[str]:
    """Every reference that would make k8s a second home for a moved name:
    setattr(k8s, "<name>"...), k8s.<name> = ..., k8s.<name>(...) — the
    string form and the attribute form both match."""
    hits = []
    for name in MOVED + CONSTANTS:
        for pattern in (rf'setattr\(\s*k8s,\s*"{name}"',
                        rf"k8s\.{name}\b"):
            hits.extend(re.findall(pattern, source))
    return hits


def test_moved_names_live_only_in_peaks() -> None:
    """Runtime identity: each moved name (functions, the class, the constant)
    IS launcher.peaks', and k8s carries no name (no facade re-export)."""
    for name in MOVED:
        impl = getattr(peaks, name)
        assert impl.__module__ == "launcher.peaks", name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"
    for name in CONSTANTS:
        assert hasattr(peaks, name), name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"


def test_single_home_via_module_import() -> None:
    """k8s reaches the sampler ONLY through the peaks module object — the
    attribute lookup that makes peaks the single home."""
    assert k8s.peaks is peaks


def test_k8s_has_no_defs_or_constants_of_moved_names() -> None:
    # RED calibration: the AST scanners see a re-introduced class def and a
    # re-introduced module constant.
    mutant = ('SAMPLE_INTERVAL_S = 10.0\n'
              'class _ResourceSampler:\n    pass\n'
              'def _peak_from_stats(stats, pod, ns):\n    return None\n')
    assert "_ResourceSampler" in _defs(mutant)
    assert "_peak_from_stats" in _defs(mutant)
    assert "SAMPLE_INTERVAL_S" in _module_constants(mutant)
    # GREEN: k8s.py defines no moved name and no moved constant.
    src = (LAUNCHER / "k8s.py").read_text(encoding="utf-8")
    leaked = sorted((set(MOVED) | set(CONSTANTS)) &
                    (_defs(src) | _module_constants(src)))
    assert leaked == [], f"k8s.py defines moved names: {leaked}"


def test_tests_ban_setattr_and_direct_refs_on_k8s_for_moved_names() -> None:
    # RED calibration: all three banned shapes are detected.
    mutant = ('    monkeypatch.setattr(k8s, "_ResourceSampler", fake)\n'
              "    k8s._node_of_pod = lambda pod, ns: None\n"
              "    k8s._peak_from_stats(stats, pod, ns)\n")
    assert len(_banned_k8s_refs(mutant)) == 3
    # GREEN: no test file reaches a moved name through k8s.
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == SELF:
            continue
        hits = _banned_k8s_refs(path.read_text(encoding="utf-8"))
        assert hits == [], f"{path.name} references k8s.<moved>: {hits}"
