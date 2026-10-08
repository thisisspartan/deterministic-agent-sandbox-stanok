"""CC-140/BL-1: `wait` / `run --follow` — one background call carries the verdict.

Before CC-140 the supervisor's §3 made the wait a SEPARATE background Bash task
(`while launch.sh status <label> | grep -q running`). In the SMOKE-02 run that
task was never issued: the supervisor launched `--background`, wrote "waiting",
and ended its turn — so no completion notification ever reached the TUI, even
though the run PASSed (evidence/smoke-tools: rc=0, verifier=PASS). `--follow`
now blocks until the run is terminal, so the ONE background task's completion
notification IS the verdict trigger; there is no separate step to forget.

Pinned here (hermetic — no Docker, no model):
  1  `wait` on a finished run prints state=done + the summary fields, rc=0
  2  `wait` on a dead marker prints state=dead
  3  `wait` on a live run hits the timeout cap -> state=timeout, rc=124
  4  `wait` on an unknown label prints state=missing
  5  `status` and `wait` share ONE source (`_status_dict`) — identical JSON
  6  the CLI wires `wait` and accepts `run ... --follow` (the sole background flag)
  7  `--follow` does NOT leak into the detached child's argv (a plain sync run)

C (PLAN-HYGIENE 2026-10-08): cmd_wait/cmd_status/_status_dict/_inner_run_argv
live in cli.py and take the Config explicitly — no hub facade.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_wait_follow.py -q
"""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

from launcher import cli
from launcher.config import Config

LAUNCHER_DIR = Path(__file__).resolve().parents[1]


def _host_cfg(tmp_path, monkeypatch, label="run1"):
    repo = tmp_path / "repo"
    repo.mkdir()
    log = tmp_path / "logs"
    log.mkdir()
    monkeypatch.delenv("STANOK_IN_CONTAINER", raising=False)
    evidence = repo / "evidence" / label
    evidence.mkdir(parents=True)
    return Config(repo_root=str(repo), log_dir=str(log)), evidence


def _run_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# --- 1: a finished run -> done -----------------------------------------------

def test_wait_done_prints_summary_fields(tmp_path, monkeypatch, capsys):
    cfg, evidence = _host_cfg(tmp_path, monkeypatch)
    (evidence / "summary.json").write_text(json.dumps({
        "rc": 0, "verifier": "PASS", "probe_result": "CLEAN-FIRST",
        "turns": 1, "session_id": "s1", "cache_hit_rate": "96.4%",
        "elapsed_s": 126, "errors": [],
    }), encoding="utf-8")
    assert cli.cmd_wait(cfg, "run1", timeout_s=0) == 0
    st = _run_json(capsys)
    assert st["state"] == "done" and st["rc"] == 0 and st["verifier"] == "PASS"
    assert st["probe_result"] == "CLEAN-FIRST"


# --- 2: a dead marker -> dead ------------------------------------------------

def test_wait_dead_marker(tmp_path, monkeypatch, capsys):
    cfg, evidence = _host_cfg(tmp_path, monkeypatch)
    child = subprocess.Popen(["true"])
    child.wait()  # reaped -> its pid is no longer alive
    (evidence / ".running").write_text(f"1700000000 {child.pid}\n", encoding="utf-8")
    assert cli.cmd_wait(cfg, "run1", timeout_s=0) == 0
    st = _run_json(capsys)
    assert st["state"] == "dead" and st["pid"] == child.pid


# --- 3: a live run -> timeout cap --------------------------------------------

def test_wait_timeout_on_live_run(tmp_path, monkeypatch, capsys):
    cfg, evidence = _host_cfg(tmp_path, monkeypatch)
    # Our own pid is alive: the state stays `running`, so timeout_s=0 must cap
    # immediately rather than sleep.
    (evidence / ".running").write_text(f"1700000000 {os.getpid()}\n", encoding="utf-8")
    assert cli.cmd_wait(cfg, "run1", timeout_s=0) == 124
    st = _run_json(capsys)
    assert st["state"] == "timeout"


# --- 4: unknown label -> missing ---------------------------------------------

def test_wait_missing_label(tmp_path, monkeypatch, capsys):
    cfg, _ = _host_cfg(tmp_path, monkeypatch)
    assert cli.cmd_wait(cfg, "run1", timeout_s=0) == 0
    assert _run_json(capsys)["state"] == "missing"


# --- 5: status and wait share one source -------------------------------------

def test_status_and_wait_agree(tmp_path, monkeypatch, capsys):
    cfg, evidence = _host_cfg(tmp_path, monkeypatch)
    (evidence / "summary.json").write_text(json.dumps({"rc": 1, "verifier": "FAIL"}),
                                           encoding="utf-8")
    assert cli.cmd_status(cfg, "run1") == 0
    status = _run_json(capsys)
    assert cli.cmd_wait(cfg, "run1", timeout_s=0) == 0
    wait = _run_json(capsys)
    assert status == wait
    assert cli._status_dict(cfg, "run1") == status  # the shared source


# --- 6: CLI wiring -----------------------------------------------------------

def test_cli_wires_wait_and_run_follow(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = dict(os.environ, STANOK_REPO=str(repo))
    py = str(LAUNCHER_DIR / "stanok.py")

    # `wait <label>` is a real subcommand routed to cmd_wait.
    proc = subprocess.run([sys.executable, py, "wait", "never-run"],
                          env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1])["state"] == "missing"

    # `run ... --follow` (the sole background flag) is accepted and takes the
    # background/launch branch: a missing ticket aborts at the ticket gate
    # (rc=13) before any launch — it does not fall through to a sync run.
    proc = subprocess.run([sys.executable, py, "run", str(repo / "no-such-ticket.md"), "f1",
                           "--follow"],
                          env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 13, proc.stdout + proc.stderr


# --- 7: --follow is a parent-only concern ------------------------------------

def test_follow_not_propagated_to_child_argv():
    cfg = Config()
    args = types.SimpleNamespace(ticket="tickets/T.md", label="lbl",
                                local_retries=cfg.default_retries,
                                extra=[], follow=True)
    inner = cli._inner_run_argv(cfg, args)
    assert "--follow" not in inner
    assert inner[-1] == "lbl"
