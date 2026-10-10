"""pod_guard — in-Pod proof that the Pod-only test guard is active
(TASK-STANOK-CC-233).

Contract (stdlib only: os, secrets):
- in_pod() returns True when the environment variable STANOK_IN_POD equals
  "1" (the marker both runner Job templates set), False when it is absent or
  holds any other value. The marker is read from the environment at call time.
- write_ok(path) returns True if a uniquely-named file can be created and
  removed inside the directory `path`; False if the attempt raises any OSError
  (EROFS/EPERM, or the directory does not exist).
"""

import os
import secrets


def in_pod() -> bool:
    """Return True when STANOK_IN_POD is set to exactly "1" in the
    environment of the running process; False when it is absent or holds any
    other value."""
    return os.environ.get("STANOK_IN_POD") == "1"


def write_ok(path: str) -> bool:
    """Return True if a uniquely-named probe file can be created and removed
    inside the directory `path`; False if the attempt raises any OSError."""
    probe = os.path.join(path, "pod-guard-" + secrets.token_hex(8))
    try:
        with open(probe, "w") as f:
            f.write("probe")
        os.remove(probe)
    except OSError:
        return False
    return True
