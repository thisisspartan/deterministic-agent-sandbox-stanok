"""bash_smoke — in-Pod live proof that the Bash tool and its tmp root work
(TASK-STANOK-CC-234).

Incident cc231/cc233: under the Pod's read-only root filesystem the CLI Bash
tool's tmp root was unwritable — every Bash call died with ENOENT. The
runtime was fixed host-side (both runner Pods mount a writable emptyDir at
/tmp and set CLAUDE_CODE_TMPDIR to it); this module computes the facts that
prove the fix holds from inside the Pod.

Contract (stdlib only: os, secrets, subprocess):
- tmp_root() returns the directory the CLI Bash tool uses: the value of the
  environment variable CLAUDE_CODE_TMPDIR if set, otherwise "/tmp". Read from
  the environment at call time.
- probe() returns a dict of computed facts about the current environment
  (never hardcoded):
    "tmp_root":          the resolved tmp root path;
    "tmp_root_writable": True if a uniquely-named file can be created and
                         removed inside it (any OSError -> False);
    "claude_dir_ok":     True if <tmp_root>/claude-<uid> (uid from
                         os.getuid()) can be CREATED — as the CLI Bash tool
                         itself does, not a pre-existing directory — and a
                         uniquely-named file can be created and removed inside
                         it (any OSError -> False);
    "bash_runs":         True if subprocess.run(["bash", "-c", "pwd"]) exits
                         0, else False.
"""

import os
import secrets
import subprocess


def tmp_root() -> str:
    """Return the directory the CLI Bash tool uses: the value of
    CLAUDE_CODE_TMPDIR if set in the environment of the running process,
    otherwise "/tmp"."""
    env = os.environ.get("CLAUDE_CODE_TMPDIR")
    return env if env is not None else "/tmp"


def _write_ok(path: str) -> bool:
    """Return True if a uniquely-named probe file can be created and removed
    inside the directory `path`; False if the attempt raises any OSError."""
    probe_file = os.path.join(path, "bash-smoke-" + secrets.token_hex(8))
    try:
        with open(probe_file, "w") as f:
            f.write("probe")
        os.remove(probe_file)
    except OSError:
        return False
    return True


def _claude_dir_ok(root: str) -> bool:
    """Return True if <root>/claude-<uid> can be created (like the CLI Bash
    tool itself does — creation, not a pre-existing directory) and written;
    False if any step raises an OSError."""
    claude_dir = os.path.join(root, f"claude-{os.getuid()}")
    try:
        os.makedirs(claude_dir, exist_ok=True)
    except OSError:
        return False
    return _write_ok(claude_dir)


def _bash_runs() -> bool:
    """Return True if `bash -c pwd` exits 0; False on a non-zero exit or if
    bash cannot be executed at all."""
    try:
        completed = subprocess.run(["bash", "-c", "pwd"], check=False)
    except OSError:
        return False
    return completed.returncode == 0


def probe() -> dict:
    """Return a dict of computed facts about the current environment: the
    resolved tmp root, whether it is writable, whether the CLI's
    claude-<uid> directory can be created and written, and whether a real
    `bash -c pwd` succeeds."""
    root = tmp_root()
    return {
        "tmp_root": root,
        "tmp_root_writable": _write_ok(root),
        "claude_dir_ok": _claude_dir_ok(root),
        "bash_runs": _bash_runs(),
    }
