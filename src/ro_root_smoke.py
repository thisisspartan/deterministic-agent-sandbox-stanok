"""ro_root_smoke — acceptance module for the readOnlyRootFilesystem Pod
hardening (SPEC-READONLY-ROOT-2026-10-10).

Contract:
- mul(a, b) returns the product of its two integer arguments.
- write_probe(path) returns True if a uniquely-named file can be created and
  removed inside the directory `path`, False if the attempt raises OSError
  (EROFS/EPERM). Stdlib only.
"""

import tempfile


def mul(a: int, b: int) -> int:
    """Return the product of a and b."""
    return a * b


def write_probe(path: str) -> bool:
    """Return True if a uniquely-named file can be created and removed inside
    the directory `path`; False if the attempt raises OSError (EROFS/EPERM,
    or the directory does not exist)."""
    try:
        with tempfile.NamedTemporaryFile(dir=path) as f:
            f.write(b"probe")
            f.flush()
        return True
    except OSError:
        return False
