"""abort — the launch-level refusal path (wave A, step 1 of the agreed k8s
split sequence: ARCHIVE/CONTEXT-2026-10-21c.md, T3 step 1 "start with
abort.py").

Extracted from launcher/cli.py (moved verbatim: _pid_alive, _early_abort).
Behavioral reference captured BEFORE the move (missing-ticket launch:
rc=13, EARLY-ABORT summary.json, failures.log) and byte-compared after
it — recorded in specs/STATUS.md.

Why a module of its own: k8s.host_launch_k8s called cli._early_abort
through a lazy `from launcher.cli import` because cli imports k8s — the
cycle was the only reason for the lazy import. Both consumers now import
this leaf module, which imports neither of them. cli re-exports both
names (facade: cli._early_abort IS this module's object; guarded by
tests_harness/test_abort_facade.py). The marker-liveness probe
_pid_alive lives here with the cleanup that needs it; cli's status path
imports it as well. Strict-class annotated from birth (mypy.ini)."""

import json
import os
from typing import TYPE_CHECKING

from launcher.exitcodes import ExitCode
from launcher.logs import log
from launcher.summary import _failure_lines, _write_failures, build_summary
from launcher.verdicts import Verdict

if TYPE_CHECKING:  # quoted annotations only: no runtime import (Pod-safe, verify.py precedent)
    from launcher.config import Config


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _early_abort(cfg: "Config", marker: str, label: str, ticket: str,
                 code: ExitCode, err_msg: str) -> int:
    """Launch-level refusal: log, clean a dead marker, write the EARLY-ABORT
    summary (only when absent — a fresh verdict must not be overwritten).

    S1: the summary goes to cfg.summary_dir(label) — inside the container the
    rw LOG_DIR/<label> mount; on the host the evidence dir (the host is the
    publisher)."""
    log(err_msg)
    if os.path.exists(marker):
        # A live run's marker must survive an early abort of a
        # concurrent launch attempt: remove it only when the
        # recorded process is dead (or the marker is unparseable).
        live = False
        try:
            with open(marker, encoding="utf-8") as f:
                pid = int(f.read().split()[-1])
            live = _pid_alive(pid)
        except (OSError, ValueError):
            pass
        if not live:
            try:
                os.remove(marker)
            except OSError:
                pass
    summary_dir = cfg.summary_dir(label)
    os.makedirs(summary_dir, exist_ok=True)
    sum_path = os.path.join(summary_dir, "summary.json")
    if not os.path.exists(sum_path):
        job = {
            "label": label,
            "ticket": ticket,
            "rc": int(code),
            "verifier": "FAIL",
            "probe_result": Verdict.EARLY_ABORT.value,
            "turns": 0,
            "error": err_msg,
        }
        with open(sum_path, "w", encoding="utf-8") as f:
            json.dump(build_summary(cfg, job, 0), f, ensure_ascii=False, indent=2)
        # CC-237 (schema v2): the refusal text goes to failures.log.
        _write_failures(summary_dir, _failure_lines(job))
    return int(code)
