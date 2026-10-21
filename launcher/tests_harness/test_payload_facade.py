"""#316 (2026-10-22): guards for the launcher.payload + summary-stamps extraction.

The agreed DoD (operator order 2026-10-22, layer finding of the pre-flight
review) moved verbatim into launcher.payload: the transport/codec cluster
(new_nonce/begin_marker/end_marker/pack_tree/unpack_tree/transport_ok/
build_payload/_bounded_gunzip/extract_payload/rewrite_tracing_endpoint and
the constants TRANSPORT_MAX_B64, PAYLOAD_MAX_DECOMPRESSED_BYTES,
PAYLOAD_TAR_OVERHEAD_BYTES, _GUNZIP_CHUNK); the host evidence stamps moved
to launcher.summary (stamp_opik_traces/_stamp_summary_identity/
_stamp_resource_peaks). Wave-A facade rule: k8s.py holds no def, no constant
and no re-export — the host reaches them as payload._X / summary._X, so a
test stub on a name in the new home intercepts every call site.

Beyond the wave-A shape, #316 is a LAYER fix, so its guards also lock the
layer claims:
  1  payload.py is a pure-stdlib leaf (imports nothing from launcher) —
     pod_runner.py runs inside the Pod and imports it directly; banned:
     any `k8s.` reference in pod_runner.py (the 1159-line host orchestrator
     must not re-enter the Pod runtime).
  2  no new cycle: summary.py imports lifecycle and opik; neither of them
     may import launcher.summary.

Calibrated RED-on-bad before use: the scanners run against in-memory
mutants that re-introduce each banned shape (def/constant in k8s.py,
setattr/direct refs on k8s in tests, k8s import or k8s. refs in
pod_runner, a launcher import in payload, a summary import in lifecycle or
opik) and against the real sources (GREEN) — no file is written, the tree
stays clean. The self-scan excludes this file (its own mutant literals
would trip the ban).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_payload_facade.py -q
"""
import ast
import re
from pathlib import Path

from launcher import k8s, payload, summary

TESTS_DIR = Path(__file__).resolve().parent
LAUNCHER = TESTS_DIR.parent
SELF = Path(__file__).resolve().name

# Names #316 moved verbatim into launcher.payload (functions and constants).
MOVED = ["new_nonce", "begin_marker", "end_marker", "pack_tree", "unpack_tree",
         "transport_ok", "build_payload", "_bounded_gunzip", "extract_payload",
         "rewrite_tracing_endpoint"]
CONSTANTS = ["TRANSPORT_MAX_B64", "PAYLOAD_MAX_DECOMPRESSED_BYTES",
             "PAYLOAD_TAR_OVERHEAD_BYTES", "_GUNZIP_CHUNK"]

# Names #316 moved verbatim into launcher.summary (host evidence stamps).
STAMPS = ["stamp_opik_traces", "_stamp_summary_identity", "_stamp_resource_peaks"]


def _defs(source: str) -> set[str]:
    tree = ast.parse(source)
    return {node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)}


def _module_constants(source: str) -> set[str]:
    tree = ast.parse(source)
    return {t.id for node in tree.body if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name)}


def _imported_modules(source: str) -> set[str]:
    """Fully-qualified module references: `from launcher import summary` and
    `import launcher.summary` both resolve to "launcher.summary" (the
    from-form carries only "launcher" as node.module — the alias is the
    module, so it must be joined)."""
    tree = ast.parse(source)
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                refs.add(node.module if alias.name == "*"
                        else f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                refs.add(alias.name)
    return refs


def _launcher_imports(source: str) -> set[str]:
    return {m for m in _imported_modules(source)
            if m == "launcher" or m.startswith("launcher.")}


def _banned_k8s_refs(source: str) -> list[str]:
    """Every reference that would make k8s a second home for a moved name:
    setattr(k8s, "<name>"...), k8s.<name> = ..., k8s.<name>(...) — the
    string form and the attribute form both match."""
    hits = []
    for name in MOVED + CONSTANTS + STAMPS:
        for pattern in (rf'setattr\(\s*k8s,\s*"{name}"',
                        rf"k8s\.{name}\b"):
            hits.extend(re.findall(pattern, source))
    return hits


def test_moved_names_live_only_in_payload_or_summary() -> None:
    """Runtime identity: each moved function IS launcher.payload's (or the
    home module's for the stamps), and k8s carries no name (no facade
    re-export)."""
    for name in MOVED:
        impl = getattr(payload, name)
        assert impl.__module__ == "launcher.payload", name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"
    for name in STAMPS:
        impl = getattr(summary, name)
        assert impl.__module__ == "launcher.summary", name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"
    for name in CONSTANTS:
        assert hasattr(payload, name), name
        assert not hasattr(k8s, name), f"k8s re-exposes {name}"


def test_single_home_via_module_import() -> None:
    """k8s reaches both homes ONLY through the module objects — the
    attribute lookups that make payload/summary the single patch homes."""
    assert k8s.payload is payload
    assert k8s.summary is summary


def test_k8s_has_no_defs_or_constants_of_moved_names() -> None:
    # RED calibration: the AST scanners see a re-introduced def and a
    # re-introduced module constant.
    mutant = ("TRANSPORT_MAX_B64 = 1\n"
              "def pack_tree(repo_root):\n    pass\n")
    assert "pack_tree" in _defs(mutant)
    assert "TRANSPORT_MAX_B64" in _module_constants(mutant)
    # GREEN: k8s.py defines no moved name and no moved constant.
    src = (LAUNCHER / "k8s.py").read_text(encoding="utf-8")
    leaked = sorted((set(MOVED) | set(CONSTANTS) | set(STAMPS)) &
                    (_defs(src) | _module_constants(src)))
    assert leaked == [], f"k8s.py defines moved names: {leaked}"


def test_tests_ban_setattr_and_direct_refs_on_k8s_for_moved_names() -> None:
    # RED calibration: all three banned shapes are detected.
    mutant = ('    monkeypatch.setattr(k8s, "pack_tree", fake)\n'
              "    k8s.extract_payload = lambda t, n: None\n"
              "    k8s.build_payload(files)\n")
    assert len(_banned_k8s_refs(mutant)) == 3
    # GREEN: no test file reaches a moved name through k8s.
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == SELF:
            continue
        hits = _banned_k8s_refs(path.read_text(encoding="utf-8"))
        assert hits == [], f"{path.name} references k8s.<moved>: {hits}"


def test_pod_runner_imports_payload_directly_not_k8s() -> None:
    """#316's whole point: the in-Pod runtime imports the pure codec module
    directly; the host orchestrator must not re-enter the Pod.
    """
    # RED calibration: the scanners see both banned forms.
    mutant = "from launcher import k8s\nfiles = k8s.build_payload(x)\n"
    assert "launcher.k8s" in _imported_modules(mutant)
    assert re.findall(r"k8s\.\w+", mutant)
    # GREEN: pod_runner imports launcher.payload and references k8s nowhere.
    src = (LAUNCHER / "pod_runner.py").read_text(encoding="utf-8")
    assert "launcher.payload" in _imported_modules(src)
    hits = re.findall(r"k8s\.\w+", src)
    assert hits == [], f"pod_runner.py references k8s: {hits}"
    cycles = {m for m in _imported_modules(src)
              if m == "launcher.k8s" or m.startswith("launcher.k8s.")}
    assert cycles == set(), f"pod_runner imports k8s: {cycles}"


def test_payload_stays_a_pure_stdlib_leaf() -> None:
    """The Pod-importability of payload.py is the layer contract: importing
    anything from launcher re-forms the pulled-in-orchestrator problem."""
    # calibration first: the AST scanner sees both import forms.
    mutant = "from launcher import k8s\nimport launcher\n"
    assert _launcher_imports(mutant) == {"launcher.k8s", "launcher"}
    mods = _launcher_imports((LAUNCHER / "payload.py").read_text(encoding="utf-8"))
    assert mods == set(), f"payload.py imports a launcher module: {mods}"


def test_no_new_cycle_summary_stays_importable_by_its_consumers() -> None:
    """summary.py imports lifecycle and opik for the stamps; a summary
    import on either side of that edge would close a cycle."""
    # calibration first: the AST scanner sees the banned import.
    mutant = "from launcher import summary\n"
    assert "launcher.summary" in _imported_modules(mutant)
    for fname in ("lifecycle.py", "opik.py"):
        mods = _imported_modules((LAUNCHER / fname).read_text(encoding="utf-8"))
        cycles = {m for m in mods
                  if m == "launcher.summary" or m.startswith("launcher.summary.")}
        assert cycles == set(), f"{fname} imports summary: {cycles}"
