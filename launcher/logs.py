"""logs — the single logging entry point (C, ARCH-REVIEW 2026-10-08).

Moved out of the hub (launcher/stanok.py) unchanged. log() prints and, when a
sink is attached, mirrors into the per-run evidence file. The sink
`_stdout_log_f` is a per-run file handle opened by cli.cmd_run and assigned
to this module global — deliberately a module global (a per-run handle, not
configuration; config lives in config.Config/RunState).
"""

# The logging sink: the handle cmd_run opens for evidence/launcher.stdout.log.
_stdout_log_f = None


def log(msg: str = "") -> None:
    print(msg, flush=True)
    if _stdout_log_f is not None:
        try:
            _stdout_log_f.write(msg + "\n")
            _stdout_log_f.flush()
        except (OSError, ValueError):
            pass
