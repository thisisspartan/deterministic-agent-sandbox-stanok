"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §3) — the runtime switch.

launch.sh keeps its contract (`run <ticket> <label> --follow`, status/wait/
stop unchanged); the runtime is selected by the STANOK_RUNTIME env: absent =
the Docker path (unchanged), "k8s" = the host orchestrator (k8s.host_launch_
k8s). The switch is a pure function so the dispatch is testable without a
cluster. Tests:
  1  default (env unset) -> "docker"
  2  STANOK_RUNTIME=k8s -> "k8s"
  3  the k8s host driver exists with the entry the dispatcher calls

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_wiring.py -q
"""
from launcher import cli, k8s


def test_default_runtime_is_docker(monkeypatch):
    monkeypatch.delenv("STANOK_RUNTIME", raising=False)
    assert cli._runtime_mode() == "docker"


def test_k8s_runtime_selected(monkeypatch):
    monkeypatch.setenv("STANOK_RUNTIME", "k8s")
    assert cli._runtime_mode() == "k8s"


def test_host_driver_entry_exists():
    assert callable(k8s.host_launch_k8s)
