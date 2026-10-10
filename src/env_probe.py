"""env_probe — in-Pod environment probes (TASK-STANOK-CC-230).

Contract (stdlib only: os, subprocess, secrets):
- bash_print(expr) returns the stripped stdout of `bash -c 'echo "<expr>"'`.
- write_error(path) returns None if a uniquely-named file can be created and
  removed inside `path` (creating `path` itself first when it does not
  exist, and removing it again afterwards); otherwise the errno (int) of the
  OSError the probe raised — errno.EROFS when the attempt lands on the
  read-only container root.
"""

import os
import secrets
import subprocess


def bash_print(expr: str) -> str:
    """Return the stripped stdout of `bash -c 'echo "<expr>"'`."""
    completed = subprocess.run(
        ["bash", "-c", 'echo "' + expr + '"'],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def write_error(path: str) -> int | None:
    """Probe whether `path` is a writable directory.

    Returns None when a uniquely-named probe file can be created and removed
    inside `path` (the directory itself is created first when absent, then
    removed again); otherwise the errno (int) of the OSError the probe
    raised — errno.EROFS on the read-only container root.
    """
    created_dir = False
    try:
        if not os.path.isdir(path):
            os.mkdir(path)
            created_dir = True
        probe = os.path.join(path, "env-probe-" + secrets.token_hex(8))
        with open(probe, "w") as f:
            f.write("probe")
        os.remove(probe)
    except OSError as exc:
        return exc.errno
    finally:
        if created_dir:
            try:
                os.rmdir(path)
            except OSError:
                pass
    return None
