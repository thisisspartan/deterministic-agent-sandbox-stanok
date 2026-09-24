"""CC-140: `wait` / `run --background --follow` — one background call carries the verdict.

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
  6  the CLI wires `wait` and accepts `run ... --follow` (no --background)
  7  `--follow` does NOT leak into the detached child's argv (a plain sync run)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_wait_follow.py -q
"""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402


def _host_paths(tmp_path, monkeypatch, label="run1"):
    repo = tmp_path / "repo"
    repo.mkdir()
    log = tmp_path / "logs"
    log.mkdir()
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    monkeypatch.setattr(stanok, "LOG_DIR", str(log))
    monkeypatch.delenv("STANOK_IN_CONTAINER", raising=False)
    evidence = repo / "evidence" / label
    evidence.mkdir(parents=True)
    return evidence


def _run_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# --- 1: a finished run -> done -----------------------------------------------

def test_wait_done_prints_summary_fields(tmp_path, monkeypatch, capsys):
    evidence = _host_paths(tmp_path, monkeypatch)
    (evidence / "summary.json").write_text(json.dumps({
        "rc": 0, "verifier": "PASS", "probe_result": "CLEAN-FIRST",
        "turns": 1, "session_id": "s1", "cache_hit_rate": "96.4%",
        "elapsed_s": 126, "errors": [],
    }), encoding="utf-8")
    assert stanok.cmd_wait("run1", timeout_s=0) == 0
    st = _run_json(capsys)
    assert st["state"] == "done" and st["rc"] == 0 and st["verifier"] == "PASS"
    assert st["probe_result"] == "CLEAN-FIRST"


# --- 2: a dead marker -> dead ------------------------------------------------

def test_wait_dead_marker(tmp_path, monkeypatch, capsys):
    evidence = _host_paths(tmp_path, monkeypatch)
    child = subprocess.Popen(["true"])
    child.wait()  # reaped -> its pid is no longer alive
    (evidence / ".running").write_text(f"1700000000 {child.pid}\n", encoding="utf-8")
    assert stanok.cmd_wait("run1", timeout_s=0) == 0
    st = _run_json(capsys)
    assert st["state"] == "dead" and st["pid"] == child.pid


# --- 3: a live run -> timeout cap --------------------------------------------

def test_wait_timeout_on_live_run(tmp_path, monkeypatch, capsys):
    evidence = _host_paths(tmp_path, monkeypatch)
    # Our own pid is alive: the state stays `running`, so timeout_s=0 must cap
    # immediately rather than sleep.
    (evidence / ".running").write_text(f"1700000000 {os.getpid()}\n", encoding="utf-8")
    assert stanok.cmd_wait("run1", timeout_s=0) == 124
    st = _run_json(capsys)
    assert st["state"] == "timeout"


# --- 4: unknown label -> missing ---------------------------------------------

def test_wait_missing_label(tmp_path, monkeypatch, capsys):
    _host_paths(tmp_path, monkeypatch)
    assert stanok.cmd_wait("run1", timeout_s=0) == 0
    assert _run_json(capsys)["state"] == "missing"


# --- 5: status and wait share one source -------------------------------------

def test_status_and_wait_agree(tmp_path, monkeypatch, capsys):
    evidence = _host_paths(tmp_path, monkeypatch)
    (evidence / "summary.json").write_text(json.dumps({"rc": 1, "verifier": "FAIL"}),
                                           encoding="utf-8")
    assert stanok.cmd_status("run1") == 0
    status = _run_json(capsys)
    assert stanok.cmd_wait("run1", timeout_s=0) == 0
    wait = _run_json(capsys)
    assert status == wait
    assert stanok._status_dict("run1") == status  # the shared source


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

    # `run ... --follow` (WITHOUT --background) is accepted and takes the
    # background/launch branch: a missing ticket aborts at the ticket gate
    # (rc=13) before any launch — it does not fall through to a sync run.
    proc = subprocess.run([sys.executable, py, "run", "no-such-ticket.md", "f1",
                           "--follow", "--direct"],
                          env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 13, proc.stdout + proc.stderr


# --- 7: --follow is a parent-only concern ------------------------------------

def test_follow_not_propagated_to_child_argv():
    args = types.SimpleNamespace(ticket="tickets/T.md", label="lbl",
                                 direct=False, local_retries=stanok.DEFAULT_RETRIES,
                                 extra=[], background=True, follow=True)
    inner = stanok._inner_run_argv(args)
    assert "--follow" not in inner and "--background" not in inner
    assert inner[-1] == "lbl"
