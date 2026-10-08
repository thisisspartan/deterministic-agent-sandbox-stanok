#!/usr/bin/env python3
"""Stanok — context-engineered Runner on a local model.

Full integration with the L1 Supervisor:
  1. Single Continuous Session (ClaudeSDKClient): retries inside ONE session (99% KV cache).
  2. Strict summary.json contract (probe_result, errors) for L1.
  3. Adaptive Contract Lock: adaptation for creating tests from scratch and a ban on weakening assertions.
  4. Cumulative Token & Cache Telemetry: exact session_hit_rate calculation.
  5. Shielded Turn Watchdog: the turn timeout (default 1800s) is a terminal DoS
     circuit breaker — asyncio.shield() keeps the turn task alive past wait_for,
     so client.interrupt() runs cleanly and summary.json is written with the
     TURN-TIMEOUT code (rc=1) without the process dying on CancelledError.
  6. Verifier-output compression: last-N raw tail, no pattern heuristics at
     all (REVIEW-KISS-CLI-FIRST §3.3; the last substring filter — CC-138).
  7. Process cleanup: guaranteed at the container boundary via `docker stop -t 5`
     (client processes spawned with start_new_session=True are outside the
     host process group — the Reaper's os.killpg(0) does not reach them).

C (ARCHITECTURE coupling decision, 2026-10-08): this module is NO LONGER the
hub. Static configuration lives in `config.Config` (explicit, passed from
cli.main), per-run mutable state in `config.RunState` (explicit, threaded).
What remains here: the rc namespace (ExitCode), the file-policy object
(SessionPlan), and logging — the logging sink `_stdout_log_f` is a per-run
file handle opened by cli.cmd_run, not configuration, so it stays a module
global by design. The PEP 562 facade is gone: callers import the functional
submodules (gates, ticket, verify, session, summary, opik) directly. Running
this file directly enters the CLI (cli.main()).
"""

import dataclasses
from enum import IntEnum

# The logging sink: the handle cmd_run opens for evidence/launcher.stdout.log.
# log() below is the single logging entry point; the sink is deliberately a
# module global (a per-run handle, not config — see the module docstring).
_stdout_log_f = None


class ExitCode(IntEnum):
    """Launch-level exit codes — the `rc` field of summary.json (strict contract).

    1  defect (exhausted retries / contract violation) / docker missing;
    13 ticket: not found, header parse error, create-edit conflict, protected edit;
    14 workspace prep error; 15 invalid label;
    16 ENV-FAIL: test runner unavailable in the image (image defect, not a red test);
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


# T1 (CC-120): the single source of file policy (invariant I1). The policy
# consumers (parse/quarantine/contract_lock/verify_gate) read from this object;
# no consumer keeps a free-floating policy list. git is always ro. Neither the
# container's rw MOUNTS nor the :ro protected set is a field: the mounts are
# derived from declared_paths by declared_carveout (T4/CC-135) and the :ro binds
# from the same manifest the post-turn diff hashes (host_ro_paths/T4b), so no
# list in the plan can drift from the ticket or go stale. (The T2 probe_specs
# placeholder was dropped when T2 was burned — CC-131; protected_paths was
# dropped with the PreToolUse hook it fed — T5/CC-137.)
@dataclasses.dataclass(frozen=True)
class SessionPlan:
    declared_paths:  tuple[str, ...]  # ticket header: impl:/test:/docs:/edit:
    # git_mode was dropped (PLAN-HYGIENE 2026-10-08): .git is always RO (I7)
    # enforced at the mount layer — a field no consumer read was dead weight.
    # CC-125: `edit:`-declared paths are MODIFIED IN PLACE, not created from
    # scratch — prepare_workspace must not quarantine them. They stay in
    # declared_paths (positive contract + contract_lock exemption).
    edit_paths:      tuple[str, ...] = ()


# ==================================================================================
# Logging and events
# ==================================================================================
def log(msg: str = "") -> None:
    print(msg, flush=True)
    if _stdout_log_f is not None:
        try:
            _stdout_log_f.write(msg + "\n")
            _stdout_log_f.flush()
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    import cli
    raise SystemExit(cli.main())
