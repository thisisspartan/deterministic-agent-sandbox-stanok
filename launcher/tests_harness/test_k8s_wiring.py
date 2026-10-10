"""CC-231 (production cutover, supersedes the P1 §3 default) — the runtime switch.

launch.sh keeps its contract (`run <ticket> <label> --follow`, status/wait/
stop unchanged); k8s is the DEFAULT runtime: absent/any other value = the
host orchestrator (k8s.host_launch_k8s); the Docker path (deprecated
fallback, launcher/sandbox.py) runs ONLY on an explicit STANOK_RUNTIME=docker,
with a loud WARNING on stderr. The switch is a pure function so the dispatch
is testable without a cluster. Tests:
  1  default (env unset) -> "k8s"
  2  STANOK_RUNTIME=docker -> "docker" (the only Docker opt-in)
  3  STANOK_RUNTIME=k8s -> "k8s" (explicit, same as default)
  4  the k8s host driver exists with the entry the dispatcher calls
  5  the explicit-Docker opt-in prints the deprecation WARNING

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_wiring.py -q
"""
from launcher import cli, k8s


def test_default_runtime_is_k8s(monkeypatch):
    monkeypatch.delenv("STANOK_RUNTIME", raising=False)
    assert cli._runtime_mode() == "k8s"


def test_docker_only_on_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("STANOK_RUNTIME", "docker")
    assert cli._runtime_mode() == "docker"
    # any other value is NOT a Docker opt-in (the old default semantics are
    # gone: a typo no longer silently selects the deprecated path)
    monkeypatch.setenv("STANOK_RUNTIME", "k8s")
    assert cli._runtime_mode() == "k8s"
    monkeypatch.setenv("STANOK_RUNTIME", "")
    assert cli._runtime_mode() == "k8s"


def test_host_driver_entry_exists():
    assert callable(k8s.host_launch_k8s)


def test_deprecated_docker_warning(capsys):
    cli._warn_deprecated_docker()
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "deprecated insecure Docker runtime" in err
    assert "seccomp/apparmor unconfined" in err
