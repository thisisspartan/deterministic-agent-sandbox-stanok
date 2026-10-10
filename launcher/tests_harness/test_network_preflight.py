"""S4 (SPEC-NETWORK-2026-10-09) — bridge network + network preflight.

Policy under test (E2): model reachable from the worker container, external
network blocked, host services closed. Enforcement: the worker runs on the
`stanok-net` bridge (iptables STANOK-NET chain, operator-managed) and the
host probes the policy BEFORE the worker starts (rc=16 refusal, rc=20 only
when the server is down for the host too).

Tests:
 1 classify_net_probe: pure classification of all outcomes —
   OK -> None; external leak -> 16; host leak -> 16; model blocked while the
   host reaches it -> 16; model down for the host too -> 20; probe None -> 16
 2 network_preflight wiring (mocked internals): network missing -> 16 before
   any probe; STANOK_SKIP_NET_PREFLIGHT=1 -> None; probe OK -> None;
   model-fail path calls the host cross-check exactly once
 3 sandbox.probe_argv: name carries the reap prefix, --network=stanok-net,
   no mounts/env, inner command python3 - <server_url>
 4 sandbox_argv worker: --network=stanok-net (not host); STANOK_DOCKER_NETWORK
   override respected; fresh argv stays --network=none
 5 wiring: _host_launch runs network_preflight BEFORE run_sandboxed and
   aborts (rc passthrough) without starting the container on failure
 6 opik_traces_field: in-container -> "disabled" (field present, not 0/null);
   outside -> the existing _opik_trace_count()
 7 NET_PROBE_SCRIPT is valid python and prints the JSON contract
   {model, external, host} (run via `python3 -` locally — no docker needed)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_network_preflight.py -q
"""
import argparse
import json
import subprocess
import sys

from launcher import cli, gates, opik, sandbox
from launcher.config import Config

OK_PROBE = {"model": True, "external": False, "host": False}


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    logdir = tmp_path / "logs"
    logdir.mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(logdir))


# --- 1: pure classification ------------------------------------------------------

def test_classify_ok_is_none():
    assert gates.classify_net_probe(OK_PROBE, True) is None


def test_classify_external_leak_is_env_fail():
    rc, msg = gates.classify_net_probe(
        {"model": True, "external": True, "host": False}, True)
    assert rc == 16 and "external" in msg


def test_classify_host_leak_is_env_fail():
    rc, msg = gates.classify_net_probe(
        {"model": True, "external": False, "host": True}, True)
    assert rc == 16 and "host" in msg


def test_classify_model_blocked_while_host_reaches_it_is_env_fail():
    rc, msg = gates.classify_net_probe(
        {"model": False, "external": False, "host": False}, True)
    assert rc == 16 and "model" in msg


def test_classify_model_down_for_host_too_is_server():
    rc, msg = gates.classify_net_probe(
        {"model": False, "external": False, "host": False}, False)
    assert rc == 20


def test_classify_probe_missing_is_env_fail():
    rc, msg = gates.classify_net_probe(None, True)
    assert rc == 16 and "probe" in msg


# --- 2: network_preflight wiring (mocked internals) ------------------------------

def _mock_preflight(monkeypatch, *, net_exists=True, probe=OK_PROBE,
                    host_ok=True):
    calls = []
    monkeypatch.setattr(gates, "_network_exists",
                        lambda net: calls.append(("net", net)) or net_exists)
    monkeypatch.setattr(gates, "_run_net_probe",
                        lambda cfg: calls.append(("probe",)) or probe)
    monkeypatch.setattr(gates, "_fetch_server_props",
                        lambda cfg: calls.append(("host",)) or
                        ({"n_ctx": 1} if host_ok else None))
    monkeypatch.delenv("STANOK_SKIP_NET_PREFLIGHT", raising=False)
    return calls


def test_network_missing_refuses_before_probe(tmp_path, monkeypatch):
    _r, cfg = _repo(tmp_path)
    calls = _mock_preflight(monkeypatch, net_exists=False)
    rc, msg = gates.network_preflight(cfg)
    assert rc == 16 and "stanok-net" in msg
    assert calls == [("net", "stanok-net")]  # no probe, no host check


def test_skip_env_short_circuits(tmp_path, monkeypatch):
    _r, cfg = _repo(tmp_path)
    calls = _mock_preflight(monkeypatch)  # delenv first, then set
    monkeypatch.setenv("STANOK_SKIP_NET_PREFLIGHT", "1")
    assert gates.network_preflight(cfg) is None
    assert calls == []


def test_probe_ok_passes(tmp_path, monkeypatch):
    _r, cfg = _repo(tmp_path)
    _mock_preflight(monkeypatch)
    assert gates.network_preflight(cfg) is None


def test_model_fail_triggers_host_crosscheck_once(tmp_path, monkeypatch):
    _r, cfg = _repo(tmp_path)
    probe = {"model": False, "external": False, "host": False}
    calls = _mock_preflight(monkeypatch, probe=probe, host_ok=True)
    rc, _msg = gates.network_preflight(cfg)
    assert rc == 16
    assert calls.count(("host",)) == 1


def test_model_down_for_host_too_is_server_rc(tmp_path, monkeypatch):
    _r, cfg = _repo(tmp_path)
    probe = {"model": False, "external": False, "host": False}
    _mock_preflight(monkeypatch, probe=probe, host_ok=False)
    rc, _msg = gates.network_preflight(cfg)
    assert rc == 20


# --- 3: probe argv -----------------------------------------------------------------

def test_probe_argv_reap_prefix_and_isolation(tmp_path):
    repo, _cfg = _repo(tmp_path)
    name, argv = sandbox.probe_argv(str(repo), "img:1", "http://10.0.0.1:8080")
    assert name.startswith(f"stanok-{repo.name}-netprobe-")  # reap prefix
    assert "--network=stanok-net" in argv
    assert "--rm" in argv and "--init" in argv
    assert not any(a.startswith("-v") for a in argv)
    assert not any(a.startswith("-e") for a in argv)
    assert argv[-3:] == ["/usr/bin/python3", "-", "http://10.0.0.1:8080"]


# --- 4: worker/fresh network --------------------------------------------------------

def test_worker_argv_uses_bridge_not_host(tmp_path, monkeypatch):
    repo, cfg = _repo(tmp_path)
    monkeypatch.delenv("STANOK_DOCKER_NETWORK", raising=False)
    _name, argv = sandbox.sandbox_argv(str(repo), cfg.log_dir, "img:1", ["x"])
    assert "--network=stanok-net" in argv
    assert "--network=host" not in argv


def test_docker_network_env_override(tmp_path, monkeypatch):
    repo, cfg = _repo(tmp_path)
    monkeypatch.setenv("STANOK_DOCKER_NETWORK", "other-net")
    _name, argv = sandbox.sandbox_argv(str(repo), cfg.log_dir, "img:1", ["x"])
    assert "--network=other-net" in argv


def test_fresh_argv_stays_network_none(tmp_path):
    repo, _cfg = _repo(tmp_path)
    _name, argv = sandbox.fresh_verify_argv(str(repo), "img:1")
    assert "--network=none" in argv


# --- 5: _host_launch wiring ---------------------------------------------------------

def _host_args(tmp_path, cfg):
    ticket_file = tmp_path / "ticket.md"
    ticket_file.write_text("test: tests/x_test.py\n", encoding="utf-8")
    return argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket_file),
                             local_retries=cfg.default_retries, extra=[])


def test_host_launch_aborts_before_container_on_net_failure(tmp_path, monkeypatch):
    repo, cfg = _repo(tmp_path)
    args = _host_args(tmp_path, cfg)
    started = []
    monkeypatch.setattr(cli, "run_sandboxed",
                        lambda *a: started.append(a) or 0)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(cli, "network_preflight",
                        lambda cfg: (16, "network 'stanok-net' missing"))
    rc = cli._host_launch(cfg, args, str(tmp_path / ".running"))
    assert rc == 16
    assert started == []  # the container never started


def test_host_launch_runs_preflight_before_run_sandboxed(tmp_path, monkeypatch):
    repo, cfg = _repo(tmp_path)
    args = _host_args(tmp_path, cfg)
    order = []
    monkeypatch.setattr(cli, "run_sandboxed",
                        lambda *a: order.append("run") or 0)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(cli, "network_preflight",
                        lambda cfg: order.append("net") or None)
    assert cli._host_launch(cfg, args, str(tmp_path / ".running")) == 0
    assert order == ["net", "run"]


# --- 6: opik_traces_field -----------------------------------------------------------

def test_opik_field_disabled_in_container(monkeypatch):
    monkeypatch.setenv("STANOK_IN_CONTAINER", "1")
    monkeypatch.setattr(opik, "_opik_trace_count", lambda: 7)
    assert opik.opik_traces_field() == "disabled"


def test_opik_field_uses_count_outside_container(monkeypatch):
    monkeypatch.delenv("STANOK_IN_CONTAINER", raising=False)
    monkeypatch.setattr(opik, "_opik_trace_count", lambda: 7)
    assert opik.opik_traces_field() == 7
    monkeypatch.setattr(opik, "_opik_trace_count", lambda: None)
    assert opik.opik_traces_field() is None


# --- 7: the probe script itself ------------------------------------------------------

def test_net_probe_script_prints_json_contract():
    sp = subprocess.run(
        [sys.executable, "-", "http://127.0.0.1:1/props"],
        input=gates.NET_PROBE_SCRIPT, capture_output=True, text=True,
        timeout=30)
    assert sp.returncode == 0, sp.stderr
    data = json.loads(sp.stdout)
    assert set(data) == {"model", "external", "host"}
    assert all(isinstance(v, bool) for v in data.values())
    assert data["model"] is False  # port 1: nothing listens
