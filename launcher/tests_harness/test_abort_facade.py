"""Wave A step 1 (2026-10-21): guards for the launcher.abort extraction.

The agreed sequence (specs/ARCHIVE/CONTEXT-2026-10-21c.md, T3 step 2)
requires for every moved name: a facade-identity guard (old reference
paths resolve to the single new implementation) and a grep-ban of the
lazy import the move removed. Moved here: cli._pid_alive / cli._early_abort
→ launcher.abort; banned: any `from launcher.cli import ...` in k8s.py —
the module cycle the lazy import existed to break must not re-form, and
abort.py itself must stay a leaf (it imports neither cli nor k8s).

Calibrated RED-on-bad before use: the source scanners are run against
in-memory mutants that re-introduce the banned imports (RED) and against
the real files (GREEN) — no file is written, the tree stays clean.
"""
import ast
import re
from pathlib import Path

from launcher import abort, cli

LAUNCHER = Path(__file__).resolve().parent.parent


def _lazy_cli_imports(source: str) -> list[str]:
    return re.findall(r"from launcher\.cli import [^\n]*", source)


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
    return mods


def test_facade_identity_old_reference_paths_resolve_to_one_impl() -> None:
    """cli._early_abort / cli._pid_alive ARE launcher.abort's objects — the
    facade rule of the agreed sequence (an import re-export, not a copy)."""
    assert cli._early_abort is abort._early_abort
    assert cli._pid_alive is abort._pid_alive
    assert abort._early_abort.__module__ == "launcher.abort"
    assert abort._pid_alive.__module__ == "launcher.abort"


def test_k8s_lazy_cli_import_banned_and_scanner_calibrated() -> None:
    source = (LAUNCHER / "k8s.py").read_text(encoding="utf-8")
    # RED calibration first: the scanner detects the banned line when present.
    mutant = source + "\nfrom launcher.cli import _early_abort\n"
    assert _lazy_cli_imports(mutant) == ["from launcher.cli import _early_abort"]
    # GREEN: the real file carries no lazy import of cli (the cycle is gone).
    assert _lazy_cli_imports(source) == [], "lazy import of cli re-appeared in k8s.py"


def test_abort_stays_a_leaf_no_new_cycle() -> None:
    """The extraction exists to break the cli<->k8s cycle; abort must not
    import either side of it."""
    # calibration first: the AST scanner sees both banned forms when present
    mutant = "import launcher.k8s\nfrom launcher.cli import main\n"
    assert {"launcher.cli", "launcher.k8s"} <= _imported_modules(mutant)
    mods = _imported_modules((LAUNCHER / "abort.py").read_text(encoding="utf-8"))
    cycles = {m for m in mods
              if m in {"launcher.cli", "launcher.k8s"}
              or m.startswith(("launcher.cli.", "launcher.k8s."))}
    assert cycles == set(), f"abort.py imports a cycle side: {cycles}"
