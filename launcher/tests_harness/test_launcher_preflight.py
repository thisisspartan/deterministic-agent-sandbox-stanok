"""W2 — launcher preflight safety net (hermetic, fake `docker` on PATH).

Pins the launch mechanisms in launcher/stanok.py:
  1  preflight_image: digest mismatch (inspect -> deadbeef) -> False, log "digest mismatch"
  2  preflight_image: image not found (inspect rc!=0) -> False
  3  preflight_image: digest OK but runner probe fails (run rc=1) -> False, log probe name
  4  preflight_image: all good -> True
  5  verify_gate: stub run.sh (test -> rc=6) -> env_fail True, "ENV-FAIL:" message
  6  _status_fields(16, "FAIL", 1) == ("ENV-FAIL", "FAIL", "ENV-FAIL")
  7  _verifier_hook: rc=6 -> {} + "ENV-FAIL" log; rc=1 -> "RED CONFIRMED" context; rc=0/2 -> {}

CC-106: the former test 8 (full path digest mismatch -> process rc=25) is
gone with the launch-path preflight — the digest check now lives in doctor
(test_doctor.py::test_docker_image_digest_matches); tests 1-4 pin the
preflight_image unit the doctor calls.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_launcher_preflight.py -q
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = REPO_ROOT / "launcher"

# Import the launcher module (pure stdlib + sandbox; the SDK is imported lazily).
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402


def _make_fake_docker(base: Path) -> Path:
    """A fake `docker` in base/fakebin honoring FAKE_DOCKER_* env vars at call time.

    - `docker inspect ...` -> prints FAKE_DOCKER_INSPECT_OUT, exits FAKE_DOCKER_INSPECT_RC
    - `docker run ...`     -> exits FAKE_DOCKER_RUN_RC
    """
    d = base / "fakebin"
    d.mkdir(exist_ok=True)
    script = d / "docker"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "inspect" ]]; then\n'
        '  printf "%s" "${FAKE_DOCKER_INSPECT_OUT:-}"\n'
        '  exit "${FAKE_DOCKER_INSPECT_RC:-0}"\n'
        "fi\n"
        'if [[ "$1" == "run" ]]; then\n'
        '  exit "${FAKE_DOCKER_RUN_RC:-0}"\n'
        "fi\n"
        "exit 0\n",
    )
    script.chmod(0o755)
    return d


@pytest.fixture()
def fake_docker(tmp_path, monkeypatch):
    d = _make_fake_docker(tmp_path)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    return d


# --- 1-4: preflight_image ------------------------------------------------------

def test_preflight_digest_mismatch(fake_docker, monkeypatch, capsys):
    monkeypatch.setattr(stanok, "_image_digest", lambda: "wantdigest")
    monkeypatch.setattr(stanok, "_stack_preflights", lambda: [])
    monkeypatch.setenv("FAKE_DOCKER_INSPECT_OUT", "deadbeef")
    monkeypatch.setenv("FAKE_DOCKER_INSPECT_RC", "0")
    assert stanok.preflight_image("stanok-machine:latest") is False
    assert "digest mismatch" in capsys.readouterr().out


def test_preflight_image_not_found(fake_docker, monkeypatch, capsys):
    monkeypatch.setattr(stanok, "_image_digest", lambda: "wantdigest")
    monkeypatch.setattr(stanok, "_stack_preflights", lambda: [])
    monkeypatch.setenv("FAKE_DOCKER_INSPECT_RC", "1")
    monkeypatch.delenv("FAKE_DOCKER_INSPECT_OUT", raising=False)
    assert stanok.preflight_image("stanok-machine:latest") is False
    assert "not found" in capsys.readouterr().out


def test_preflight_runner_probe_fails(fake_docker, monkeypatch, capsys):
    probe = "uv run --no-project pytest --version"
    monkeypatch.setattr(stanok, "_image_digest", lambda: "wantdigest")
    monkeypatch.setattr(stanok, "_stack_preflights", lambda: [probe])
    monkeypatch.setenv("FAKE_DOCKER_INSPECT_OUT", "wantdigest")
    monkeypatch.setenv("FAKE_DOCKER_INSPECT_RC", "0")
    monkeypatch.setenv("FAKE_DOCKER_RUN_RC", "1")
    assert stanok.preflight_image("stanok-machine:latest") is False
    out = capsys.readouterr().out
    assert "runner unavailable in image" in out
    assert probe in out


def test_preflight_all_good(fake_docker, monkeypatch, capsys):
    monkeypatch.setattr(stanok, "_image_digest", lambda: "wantdigest")
    monkeypatch.setattr(stanok, "_stack_preflights", lambda: ["uv run --no-project pytest --version"])
    monkeypatch.setenv("FAKE_DOCKER_INSPECT_OUT", "wantdigest")
    monkeypatch.setenv("FAKE_DOCKER_INSPECT_RC", "0")
    monkeypatch.setenv("FAKE_DOCKER_RUN_RC", "0")
    assert stanok.preflight_image("stanok-machine:latest") is True
    assert "all stack runners available" in capsys.readouterr().out


# --- 5: verify_gate env_fail ---------------------------------------------------

def test_verify_gate_env_fail(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "scripts" / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "list" ]]; then echo "tests/t_test.py"; exit 0; fi\n'
        'if [[ "$1" == "test" ]]; then exit 6; fi\n'
        "exit 0\n",
    )
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    plan = stanok.SessionPlan(
        declared_paths=(), mutable_paths=())
    ok, failures, env_fail = stanok.verify_gate(plan)
    assert ok is False
    assert env_fail is True
    assert any(msg.startswith("ENV-FAIL:") for _, msg in failures)


# --- 6: _status_fields ---------------------------------------------------------

def test_status_fields_env_fail():
    assert stanok._status_fields(16, "FAIL", 1) == ("ENV-FAIL", "FAIL", "ENV-FAIL")


# --- 7: _verifier_hook rc semantics --------------------------------------------

def _verifier_repo(base: Path, name: str, test_rc: int) -> Path:
    repo = base / name
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    assert True\n")
    (repo / "scripts" / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "test" ]]; then exit ' + str(test_rc) + "; fi\n"
        "exit 0\n",
    )
    return repo


def test_verifier_hook_rc_semantics(tmp_path, monkeypatch, capsys):
    # rc=6 -> {} + ENV-FAIL log (no RED)
    repo6 = _verifier_repo(tmp_path, "repo6", 6)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo6))
    res = asyncio.run(stanok._verifier_hook(
        {"tool_input": {"file_path": str(repo6 / "tests" / "t_test.py")}}, "toolu_1", None))
    assert res == {}
    assert "ENV-FAIL" in capsys.readouterr().out

    # rc=1 -> RED CONFIRMED context + log
    repo1 = _verifier_repo(tmp_path, "repo1", 1)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo1))
    res = asyncio.run(stanok._verifier_hook(
        {"tool_input": {"file_path": str(repo1 / "tests" / "t_test.py")}}, "toolu_1", None))
    assert "RED CONFIRMED" in res["hookSpecificOutput"]["additionalContext"]
    assert "RED CONFIRMED" in capsys.readouterr().out

    # rc=0 / rc=2 -> {} (silent)
    for rc in (0, 2):
        repok = _verifier_repo(tmp_path, f"repok{rc}", rc)
        monkeypatch.setattr(stanok, "REPO_ROOT", str(repok))
        res = asyncio.run(stanok._verifier_hook(
            {"tool_input": {"file_path": str(repok / "tests" / "t_test.py")}}, "toolu_1", None))
        assert res == {}


def test_verifier_hook_call_logged(tmp_path, monkeypatch, capsys):
    # W8 double-hook diagnosis: EVERY invocation logs HOOK-CALL id=<tool_use_id>
    # at entry — including early-return paths (file outside tests/).
    repo = _verifier_repo(tmp_path, "repolog", 1)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    asyncio.run(stanok._verifier_hook(
        {"tool_input": {"file_path": str(repo / "tests" / "t_test.py")}}, "toolu_42", None))
    assert "HOOK-CALL id=toolu_42" in capsys.readouterr().out
    # early-return path (file outside tests/) still logs the call
    res = asyncio.run(stanok._verifier_hook(
        {"tool_input": {"file_path": str(repo / "src" / "x.js")}}, "toolu_43", None))
    assert res == {}
    assert "HOOK-CALL id=toolu_43" in capsys.readouterr().out
