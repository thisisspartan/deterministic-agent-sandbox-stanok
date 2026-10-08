"""exitcodes — the launch-level rc namespace (C, ARCH-REVIEW 2026-10-08).

Moved out of the hub (launcher/stanok.py) unchanged. This is the contract of
the `rc` field of summary.json; the CLI epilog points here and
test_cli_help.py pins that pointer as user-visible documentation. A new rc
goes here + the gate order in cli.main() (ARCHITECTURE.md "Where to change
what").
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """Launch-level exit codes — the `rc` field of summary.json (strict contract).

    1  defect (exhausted retries / contract violation) / docker missing;
    13 ticket: not found, header parse error, create-edit conflict, protected edit,
       zone-symlink ban (symlink in a writable zone);
    14 workspace prep error; 15 invalid label;
    16 ENV-FAIL: test runner unavailable in the image (image defect, not a red test),
       zone-symlink scan failure (broken filesystem is not a ticket defect);
    17 background child died before writing the .running marker;
    20 server unavailable / context window fail-closed;
    21 lock held by another run; 22 dirty machine tree;
    24 role leak (parent CLAUDE.md above the repo);
    26 hidden/TEMP files in src/tests/docs/scripts;
    27 test-config files under tests/ (verdict-subversion, CC-151);
    28 sandbox.filesystem deny entry invalid (CC-107/CC-157).
    """
    DEFECT = 1
    TICKET = 13
    WORKSPACE = 14
    BAD_LABEL = 15
    ENV_FAIL = 16
    CHILD_DIED = 17
    SERVER = 20
    LOCK = 21
    DIRTY_TREE = 22
    ROLE_LEAK = 24
    HIDDEN_FILES = 26
    TEST_CONFIG = 27
    SANDBOX_CONFIG = 28
