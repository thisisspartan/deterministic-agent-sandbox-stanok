"""Auto-pin hook portability guard (origin: review C5 2026-10-17).

hooks/stanok-post-commit is part of the required behavior of a published
parent (a parent with a stanok submodule must keep its gitlink current).
The sync-skeleton mirror was retired 2026-10-21 (operator decision:
publication = direct push of the tracked tree; see parent .gitignore);
this guard survives the retirement unchanged: the hook must carry no
machine-local absolute paths or private IPs (public-tree hygiene).

Layout guard: the hook lives in the PARENT repo. In a standalone stanok
checkout it is absent — skip with an explicit reason, never a silent green
(same pattern as the doctor guards).
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT.parent / "hooks" / "stanok-post-commit"

pytestmark = pytest.mark.skipif(
    not HOOK.is_file(),
    reason="parent repo not present (standalone stanok checkout) — "
    "hooks/stanok-post-commit absent",
)


def test_hook_is_portable_no_machine_local_paths():
    body = HOOK.read_text(encoding="utf-8")
    for marker in ("/home/", "/Users/", "192.168."):
        assert marker not in body, f"hook carries machine-local marker {marker!r}"
