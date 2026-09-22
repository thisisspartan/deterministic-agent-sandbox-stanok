"""commit-msg hook: TASK-ID gate + exact maintenance-prefix allowlist.

The hook is the ONLY enforcement of the commit-message contract (the
supervisor paths no longer use --no-verify), so it must actually enforce:
accept TASK-STANOK-CC-NNN and the four exact maintenance prefixes
(trailing space required), reject everything else.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_commit_msg_hook.py -q
"""
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "commit-msg"


def _run_hook(msg: str) -> int:
    f = Path(f"/tmp/stanok-commit-msg-test-{abs(hash(msg))}.txt")
    f.write_text(msg + "\n", encoding="utf-8")
    try:
        p = subprocess.run(["bash", str(HOOK), str(f)],
                           capture_output=True, text=True, timeout=10)
        return p.returncode
    finally:
        f.unlink(missing_ok=True)


def test_task_id_accepted():
    assert _run_hook("feat: add module (TASK-STANOK-CC-103)") == 0


def test_save_state_prefix_accepted():
    assert _run_hook("chore: save state before ticket") == 0
    assert _run_hook("chore: save state before e2e") == 0


def test_clean_for_task_prefix_accepted():
    assert _run_hook("chore: clean for new task — infra only") == 0


def test_sync_infra_prefix_accepted():
    assert _run_hook("chore: sync infra from darkcast (2026-09-22)") == 0


def test_harness_prefix_accepted():
    assert _run_hook("chore: harness sandbox denyRead + sync-infra prefix") == 0


def test_unrecognized_messages_rejected():
    assert _run_hook("feat: something") == 1
    # Prefixes without the trailing space must NOT pass.
    assert _run_hook("chore: save state") == 1
    assert _run_hook("chore: clean for new tasks") == 1
