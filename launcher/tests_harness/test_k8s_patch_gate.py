"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §6, operator gate 2026-10-10) —
the patch gate.

Before the host applies or fresh-checks changes.patch it must explicitly
REJECT a patch that creates a symlink (git filemode 120000) or carries a
path with a `..` segment — the zone/symlink invariants of the Docker era
(zone_symlink_gate rc=13, SEC-01) re-asserted on the transport layer.
A violation is a host-issued CONTRACT-FAIL (rc=1, probe_result), never a
silent apply. Tests:
  1  a clean new-file patch passes
  2  an empty patch passes (no-op runs are legal)
  3  `new file mode 120000` -> SYMLINK violation naming the path
  4  a `..` segment in a diff path -> TRAVERSAL violation

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_patch_gate.py -q
"""
from launcher import k8s

CLEAN = """diff --git a/src/m.py b/src/m.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/src/m.py
@@ -0,0 +1 @@
+def f(): pass
"""

SYMLINK = """diff --git a/src/link b/src/link
new file mode 120000
index 0000000..2222222
--- /dev/null
+++ b/src/link
@@ -0,0 +1 @@
+../launcher
"""

TRAVERSAL = """diff --git a/src/../outside.py b/src/../outside.py
new file mode 100644
--- /dev/null
+++ b/src/../outside.py
@@ -0,0 +1 @@
+x
"""


def test_clean_patch_passes():
    assert k8s.patch_gate(CLEAN) == []


def test_empty_patch_passes():
    assert k8s.patch_gate("") == []


def test_symlink_rejected():
    v = k8s.patch_gate(SYMLINK)
    assert any("SYMLINK" in x and "src/link" in x for x in v)


def test_traversal_rejected():
    v = k8s.patch_gate(TRAVERSAL)
    assert any("TRAVERSAL" in x for x in v)
