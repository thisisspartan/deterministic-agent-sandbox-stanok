#!/usr/bin/env python3
"""Stanok — the entry shell (C, ARCH-REVIEW 2026-10-08).

This file owns NOTHING. The hub is gone: the rc namespace lives in
`launcher/exitcodes.py`, the file-policy object (SessionPlan, the single
source of file policy — I1) in `launcher/plan.py`, logging in
`launcher/logs.py`, configuration in `launcher/config.py`. The runner
guarantees (single continuous session, shielded turn watchdog, contract
lock, telemetry, verifier-output compression, process cleanup) and the
module map are in ARCHITECTURE.md.

What remains is the script-style entry point shared by the three call
sites (launch.sh, the container argv `python3 launcher/stanok.py run ...`,
the background self-spawn in cli.launch_background): script invocation
keeps sys.path[0] = launcher/, which is NOT enough for the package
imports — add the repo root, then run the package CLI. All production code
runs through `launcher.*` modules.
"""

if __name__ == "__main__":
    import os
    import sys

    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from launcher.cli import main
    raise SystemExit(main())
