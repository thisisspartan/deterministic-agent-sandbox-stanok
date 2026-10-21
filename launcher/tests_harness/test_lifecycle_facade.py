"""Wave A portion 6 (2026-10-21): guards for the launcher.lifecycle extraction.

The agreed sequence (specs/ARCHIVE/CONTEXT-2026-10-21c.md, T3) requires for
every moved name a guard that it lives ONLY in the new module: k8s.py holds
no def, no constant and no re-export of the Pod-lifecycle observation names,
and no test patches or reads k8s.<moved> any more (the patch sites were
re-bound to lifecycle together with the move — single home: the k8s call-site
clusters host_launch_k8s and _fresh_job reach the helpers as lifecycle._X,
and they resolve their internal calls (_job_rc_and_tail -> _pod_of_job)
through this module's globals, so a test stub on a name here intercepts
every call site). The setattr's on the SHARED module objects (kube._kubectl,
k8s.subprocess, the time module) stay: those are the same module object in
every importer (portion-2 precedent). What deliberately stays in k8s is the
Job CONSTRUCTION policy the observation windows are measured against —
_DEADLINE_MARGIN_S and job_deadline (pinned directly by
test_k8s_manifests.py:330-334), _fresh_job and _image_ref — this guard
therefore checks the MOVED names only, and test_timer_contract legitimately
spans both homes (k8s.job_deadline + lifecycle graces).

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

from launcher import k8s, lifecycle

TESTS_DIR = Path(__file__).resolve().parent
LAUNCHER = TESTS_DIR.parent
SELF = Path(__file__).resolve().name

# The names wave A portion 6 moved verbatim into launcher.lifecycle: the
# Pod/Job observation cluster and the two post-deadline observation graces
# the shared-end calculator (_observation_timeout) is measured against.
MOVED = ["_pod_of_job", "_pod_image_id", "_stream_pod_logs",
         "_job_rc_and_tail", "_pod_infra_cause", "_job_infra_cause",
         "_wait_job_terminal", "_observation_timeout"]
CONSTANTS = ["_STREAM_GRACE_S", "_TERMINAL_GRACE_S"]


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


def test_moved_names_live_only_in_lifecycle() -> None:
    """Runtime identity: each moved name (the observation helpers, the
    shared-end calculator) IS launcher.lifecycle's, and k8s carries no name
    (no facade re-export); the graces are constants on lifecycle only."""
    for name in MOVED:
        impl = getattr(lifecycle, name)
        assert callable(impl), name
        assert impl.__module__ == "launcher.lifecycle", name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"
    for name in CONSTANTS:
        assert hasattr(lifecycle, name), name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"


def test_single_home_via_module_import() -> None:
    """k8s reaches the observation cluster ONLY through the lifecycle module
    object — the attribute lookup that makes lifecycle the single home."""
    assert k8s.lifecycle is lifecycle


def test_k8s_has_no_defs_or_constants_of_moved_names() -> None:
    # RED calibration: the AST scanners see a re-introduced observation def
    # and re-introduced grace constants.
    mutant = ('_STREAM_GRACE_S = 180\n_TERMINAL_GRACE_S = 60\n'
              'def _wait_job_terminal(name, ns, timeout_s):\n    return ""\n'
              'def _observation_timeout(obs_start, deadline, grace_s):\n'
              '    return 0\n')
    assert "_wait_job_terminal" in _defs(mutant)
    assert "_observation_timeout" in _defs(mutant)
    assert "_STREAM_GRACE_S" in _module_constants(mutant)
    assert "_TERMINAL_GRACE_S" in _module_constants(mutant)
    # GREEN: k8s.py defines no moved name and no moved constant.
    src = (LAUNCHER / "k8s.py").read_text(encoding="utf-8")
    leaked = sorted((set(MOVED) | set(CONSTANTS)) &
                    (_defs(src) | _module_constants(src)))
    assert leaked == [], f"k8s.py defines moved names: {leaked}"


def test_tests_ban_setattr_and_direct_refs_on_k8s_for_moved_names() -> None:
    # RED calibration: all three banned shapes are detected.
    mutant = ('    monkeypatch.setattr(k8s, "_wait_job_terminal", fake)\n'
              "    k8s._pod_of_job = lambda *a: None\n"
              "    k8s._observation_timeout(obs_start, deadline, grace)\n")
    assert len(_banned_k8s_refs(mutant)) == 3
    # GREEN: no test file reaches a moved name through k8s.
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == SELF:
            continue
        hits = _banned_k8s_refs(path.read_text(encoding="utf-8"))
        assert hits == [], f"{path.name} references k8s.<moved>: {hits}"
