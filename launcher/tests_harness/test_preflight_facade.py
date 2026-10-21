"""Wave A portion 3 (2026-10-21): guards for the launcher.preflight extraction.

The agreed sequence (specs/ARCHIVE/CONTEXT-2026-10-21c.md, T3) requires for
every moved name a guard that it lives ONLY in the new module: k8s.py holds
no def and no re-export of the preflight names, and no test patches or reads
k8s.<moved> any more (the patch sites were re-bound to preflight together
with the move — single patch home: host_launch_k8s reaches the gate as
preflight._preflight, and _preflight's composition resolves the seven
checks through this module's globals, so a test stub on a name here
intercepts every call site).

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

from launcher import k8s, preflight

TESTS_DIR = Path(__file__).resolve().parent
LAUNCHER = TESTS_DIR.parent
SELF = Path(__file__).resolve().name

# The names wave A portion 3 moved verbatim into launcher.preflight: the
# CC-232 cluster gate, the unified gate and its seven checks (_preflight's
# composition resolves them through this module's globals), the _disk_path
# helper, and the two module constants they share.
MOVED = ["_preflight", "_preflight_cluster", "_preflight_disk",
         "_preflight_image_label", "_preflight_opik",
         "_preflight_runtime_class", "_preflight_netpol",
         "_preflight_dangling", "_disk_path"]
CONSTANTS = ["DISK_MAX_PERCENT", "_NETPOL_PREFIXES"]


def _defs(source: str) -> set[str]:
    tree = ast.parse(source)
    return {node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)}


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


def test_moved_names_live_only_in_preflight() -> None:
    """Runtime identity: each moved function IS launcher.preflight's, and
    k8s carries no name (no facade re-export)."""
    for name in MOVED:
        impl = getattr(preflight, name)
        assert impl.__module__ == "launcher.preflight", name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"
    for name in CONSTANTS:
        assert hasattr(preflight, name), name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"


def test_single_home_via_module_import() -> None:
    """k8s reaches the gate ONLY through the preflight module object — the
    attribute lookup that makes preflight the single patch home."""
    assert k8s.preflight is preflight


def test_k8s_has_no_defs_or_constants_of_moved_names() -> None:
    # RED calibration: the AST scanners see a re-introduced def and a
    # re-introduced module constant.
    mutant = ("DISK_MAX_PERCENT = 99\n"
              "def _preflight(cfg):\n    pass\n")
    assert "_preflight" in _defs(mutant)
    assert "DISK_MAX_PERCENT" in _module_constants(mutant)
    # GREEN: k8s.py defines no moved name and no moved constant.
    src = (LAUNCHER / "k8s.py").read_text(encoding="utf-8")
    leaked = sorted((set(MOVED) | set(CONSTANTS)) &
                    (_defs(src) | _module_constants(src)))
    assert leaked == [], f"k8s.py defines moved names: {leaked}"


def test_tests_ban_setattr_and_direct_refs_on_k8s_for_moved_names() -> None:
    # RED calibration: all three banned shapes are detected.
    mutant = ('    monkeypatch.setattr(k8s, "_preflight", fake)\n'
              "    k8s._disk_path = lambda cfg: '/'\n"
              "    k8s._preflight_cluster(cfg)\n")
    assert len(_banned_k8s_refs(mutant)) == 3
    # GREEN: no test file reaches a moved name through k8s.
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == SELF:
            continue
        hits = _banned_k8s_refs(path.read_text(encoding="utf-8"))
        assert hits == [], f"{path.name} references k8s.<moved>: {hits}"
