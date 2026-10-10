"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §6, operator gate 2026-10-10) —
the patch gate.

Before the host applies or fresh-checks changes.patch it must explicitly
REJECT a patch that creates a symlink (git filemode 120000) or carries a
path with a `..` segment — the zone/symlink invariants of the Docker era
(zone_symlink_gate rc=13, SEC-01) re-asserted on the transport layer.
A violation is a host-issued CONTRACT-FAIL (rc=1, probe_result), never a
silent apply. Package 1 (operator spec 2026-10-10) hardens the gate: EVERY
path-bearing header is checked (diff --git, ---/+++, rename from/to, copy
from/to), paths are rejected for absolute form, '..' segments and '.git'
components (.gitignore is a normal file); gitlinks (mode 160000 in any
form, 'Subproject commit' lines) are rejected. Patch identity: SHA-256 of
the exact bytes, re-verified before every apply. Tests:
  1  a clean new-file patch passes
  2  an empty patch passes (no-op runs are legal)
  3  `new file mode 120000` -> SYMLINK violation naming the path
  4  a `..` segment in a diff path -> TRAVERSAL violation
  5  an absolute path in a ---/+++ header -> ABSOLUTE violation
  6  a '.git' component (source or destination) -> GITDIR violation
  7  absolute/.git paths in rename/copy headers -> rejected
  8  gitlink 160000 (new file / mode change / Subproject commit) -> GITLINK
  9  safe rename/copy and .gitignore patches pass
 10  patch_sha256/patch_identity_ok: the on-disk file must match the hash
 11  strict_patch_text: invalid UTF-8 bytes RAISE (no U+FFFD substitution —
     the gate/scratch must see exactly the text whose bytes are hashed)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_patch_gate.py -q
"""
import hashlib
import os

import pytest

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


# --- Package 1 (operator spec 2026-10-10): hardened gate cases ----------

ABSOLUTE = """diff --git a/src/m.py b/src/m.py
--- /etc/passwd
+++ b/src/m.py
@@ -1 +1 @@
-x
+y
"""

GITDIR_SRC = """diff --git a/.git/config b/.git/config
--- a/.git/config
+++ b/.git/config
@@ -1 +1 @@
-x
+y
"""

GITDIR_DEST = """diff --git a/src/m.py b/.git/hooks/pre-commit
new file mode 100644
--- /dev/null
+++ b/.git/hooks/pre-commit
@@ -0,0 +1 @@
+x
"""

RENAME_ABSOLUTE = """diff --git a/src/a.py b/src/b.py
similarity index 100%
rename from /etc/passwd
rename to src/b.py
"""

COPY_GITDIR = """diff --git a/src/a.py b/src/a.py
similarity index 100%
copy from .git/config
copy to src/a.py
"""

GITLINK_NEW = """diff --git a/vendor/lib b/vendor/lib
new file mode 160000
index 0000000..1111111
--- /dev/null
+++ b/vendor/lib
@@ -0,0 +1 @@
+Subproject commit 1111111111111111111111111111111111111111
"""

GITLINK_MODE = """diff --git a/vendor/lib b/vendor/lib
old mode 100644
new mode 160000
"""

GITLINK_DELETED = """diff --git a/vendor/lib b/vendor/lib
deleted file mode 160000
--- a/vendor/lib
+++ /dev/null
@@ -1 +0,0 @@
-Subproject commit 1111111111111111111111111111111111111111
"""

SAFE_RENAME = """diff --git a/src/a.py b/src/b.py
similarity index 95%
rename from src/a.py
rename to src/b.py
--- a/src/a.py
+++ b/src/b.py
@@ -1 +1 @@
-old
+new
"""

SAFE_COPY = """diff --git a/src/b.py b/src/b.py
similarity index 100%
copy from src/a.py
copy to src/b.py
"""

GITIGNORE_OK = """diff --git a/.gitignore b/.gitignore
--- a/.gitignore
+++ b/.gitignore
@@ -1 +1 @@
-old
+new
"""


def test_absolute_path_rejected():
    v = k8s.patch_gate(ABSOLUTE)
    assert any("ABSOLUTE" in x and "/etc/passwd" in x for x in v)


def test_gitdir_source_rejected():
    v = k8s.patch_gate(GITDIR_SRC)
    assert any("GITDIR" in x and ".git/config" in x for x in v)


def test_gitdir_destination_rejected():
    v = k8s.patch_gate(GITDIR_DEST)
    assert any("GITDIR" in x and ".git/hooks/pre-commit" in x for x in v)


def test_rename_absolute_rejected():
    v = k8s.patch_gate(RENAME_ABSOLUTE)
    assert any("ABSOLUTE" in x and "/etc/passwd" in x for x in v)


def test_copy_gitdir_rejected():
    v = k8s.patch_gate(COPY_GITDIR)
    assert any("GITDIR" in x and ".git/config" in x for x in v)


def test_gitlink_new_file_rejected():
    v = k8s.patch_gate(GITLINK_NEW)
    assert any("GITLINK" in x and "vendor/lib" in x for x in v)


def test_gitlink_mode_change_rejected():
    v = k8s.patch_gate(GITLINK_MODE)
    assert any("GITLINK" in x and "vendor/lib" in x for x in v)


def test_gitlink_deleted_rejected():
    v = k8s.patch_gate(GITLINK_DELETED)
    assert any("GITLINK" in x for x in v)


def test_gitlink_index_form_rejected():
    # git renders a submodule CONTENT change as `index <sha>..<sha> 160000`
    # with no mode line — the gate must catch this form too.
    patch = """diff --git a/vendor/lib b/vendor/lib
index 1111111..2222222 160000
--- a/vendor/lib
+++ b/vendor/lib
@@ -1 +1 @@
-Subproject commit 1111111111111111111111111111111111111111
+Subproject commit 2222222222222222222222222222222222222222
"""
    v = k8s.patch_gate(patch)
    assert any("GITLINK" in x and "vendor/lib" in x for x in v)


def test_safe_rename_passes():
    assert k8s.patch_gate(SAFE_RENAME) == []


def test_safe_copy_passes():
    assert k8s.patch_gate(SAFE_COPY) == []


def test_gitignore_is_not_gitdir():
    # '.git' as an exact path component is the boundary; '.gitignore' is a
    # normal file and must pass.
    assert k8s.patch_gate(GITIGNORE_OK) == []


# --- Encoding gap (operator review 2026-10-10): strict decoding ----------

INVALID_UTF8 = (b"diff --git a/src/m.py b/src/m.py\n"
                b"--- a/src/m.py\n+++ b/src/m.py\n"
                b"@@ -1 +1 @@\n-x\x80\x81\xff\n+y\n")


def test_strict_patch_text_rejects_invalid_utf8():
    # RED fixture: bytes that are not valid UTF-8 must RAISE. The gate and
    # the scratch contract must see exactly the text whose bytes are hashed
    # and applied — errors="replace" (U+FFFD) would verify a contract against
    # a tree different from the one that gets applied.
    with pytest.raises(UnicodeDecodeError):
        k8s.strict_patch_text(INVALID_UTF8)


def test_strict_patch_text_passes_valid_utf8():
    assert k8s.strict_patch_text(CLEAN.encode("utf-8")) == CLEAN


def test_patch_identity(tmp_path):
    # The hash is of the EXACT bytes; the on-disk file must match it, and a
    # missing or altered file must fail the re-verification (fail closed).
    patch_bytes = CLEAN.encode("utf-8")
    expected = hashlib.sha256(patch_bytes).hexdigest()
    assert k8s.patch_sha256(patch_bytes) == expected
    f = tmp_path / "changes.patch"
    f.write_bytes(patch_bytes)
    assert k8s.patch_identity_ok(str(f), expected)
    f.write_bytes(patch_bytes + b"\n# tampered\n")
    assert not k8s.patch_identity_ok(str(f), expected)
    f.unlink()
    assert not k8s.patch_identity_ok(str(f), expected)
