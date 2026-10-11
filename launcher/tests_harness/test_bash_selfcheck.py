"""CC-234 startup Bash self-check (session._bash_selfcheck).

Incident cc231/cc233 (trace audit 2026-10-11): under the Pod's
readOnlyRootFilesystem the CLI Bash tool's tmp root (/tmp/claude-<uid>)
was unwritable — every Bash call died ENOENT, the agent wrote blind for
the whole run, and the host verdict was still PASS. The self-check
reproduces the CLI's exact path (CLAUDE_CODE_TMPDIR || /tmp, then
"claude-<uid>", cli.js 2.1.88) BEFORE the model starts: mkdir + probe
file + `bash -c pwd`. Failure = ENV-FAIL (rc=16), no model token spent.
"""
import os

from launcher import session


def test_selfcheck_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path))
    job = {}
    assert session._bash_selfcheck(job) is None
    probe = tmp_path / f"claude-{os.getuid()}"  # the CLI's exact path
    assert probe.is_dir()
    assert not (probe / "stanok-selfcheck").exists()  # probe file removed
    assert job == {}  # a passing self-check writes nothing into the job


def test_selfcheck_readonly_root_is_envfail(tmp_path, monkeypatch):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)  # the Pod pre-CC-234 situation: cannot mkdir inside
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(ro))
    job = {}
    rc = session._bash_selfcheck(job)
    ro.chmod(0o700)  # let pytest clean up
    assert rc == 16  # ExitCode.ENV_FAIL
    assert job["verifier"] == "FAIL"
    assert "ENV-FAIL" in job["error"]
    assert job["turns"] == 0  # no turn was ever started


def test_session_stops_before_model_on_envfail(tmp_path, monkeypatch):
    # Wiring: run_continuous_session runs the self-check BEFORE the client
    # is created — a broken tmp root never instantiates the CLI.
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(ro))

    class _NoClient:
        def __init__(self, *a, **k):
            raise AssertionError("client created despite ENV-FAIL")

    import claude_agent_sdk
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", _NoClient)
    job = {"label": "selfcheck-wiring"}
    # cfg/run_state/plan are never touched when the self-check fails first.
    import asyncio
    rc = asyncio.run(
        session.run_continuous_session(None, None, job, "prompt", 0, None))
    ro.chmod(0o700)
    assert rc == 16
