"""Verdict-safety net for the launcher (hermetic, no docker, no SDK).

Pins the fail-closed verdict paths in launcher/stanok.py:
  1  _validate_declared_path: a bare zone name (`src`, `tests/`, `scripts`)
     is rejected — it is not a file and must not be quarantined; file paths
     inside the zones are accepted; absolute/`..` paths stay rejected
  2  verify_gate: `run.sh list` rc!=0 with claimed tests on stdout -> a
     `(list)` failure is recorded (the unrun test must not pass silently)
  3  verify_gate: `run.sh list` rc!=0 with empty stdout -> the stderr reason
     is surfaced as a `(list)` failure, not the generic "no tests" message
  4  verify_gate: `run.sh list` rc=0 with no tests -> `(no tests)` (regression)
  5  _contract_lock_forced_fail: non-empty cumulative violations -> FAIL +
     rc 1, violations mirrored into failures; clean job -> None
  6  _rotate_stale_summary: stale summary.json (no .running marker) is
     rotated to summary.json.prev; a live run's summary (marker present)
     is untouched; absent summary is a no-op
  7  verify_gate suite mode (D4/CC-149): ONE `test --all` call per turn —
     rc=0 pass / rc=1 a (suite) failure / rc=6 ENV-FAIL / rc=124 TIMEOUT /
     rc=2 (no suite mode) falls back to per-file spawns

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_verdict_safety.py -q
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = REPO_ROOT / "launcher"

# Import the launcher module (pure stdlib + sandbox; the SDK is imported lazily).
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402


# --- 1: _validate_declared_path ------------------------------------------------

def test_declared_path_bare_zone_rejected():
    for rel in ("src", "tests", "docs", "scripts", "src/", "tests/"):
        assert stanok._validate_declared_path(rel) is False, rel


def test_declared_path_file_accepted():
    for rel in ("src/x.py", "tests/t_test.py", "docs/m.md", "scripts/run.sh"):
        assert stanok._validate_declared_path(rel) is True, rel


def test_declared_path_traversal_rejected():
    for rel in ("/etc/passwd", "./src/x.py", "../x", "src/../tests/x"):
        assert stanok._validate_declared_path(rel) is False, rel


# --- 2-4: verify_gate `list` rc handling ---------------------------------------

def _empty_plan():
    return stanok.SessionPlan(
        declared_paths=(), mutable_paths=(),
    )


def _list_repo(base: Path, name: str, list_stdout: str, list_stderr: str,
               list_rc: int) -> Path:
    """A tmp repo whose stub run.sh `list` cats list.out/list.err and exits
    list_rc (run.sh runs with cwd=repo root, so the payloads are relative)."""
    repo = base / name
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "list.out").write_text(list_stdout, encoding="utf-8")
    (repo / "list.err").write_text(list_stderr, encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "list" ]]; then\n'
        "  cat list.out\n"
        "  cat list.err >&2\n"
        f"  exit {list_rc}\n"
        'fi\n'
        'if [[ "$1" == "test" ]]; then exit 0; fi\n'
        "exit 0\n",
    )
    return repo


def test_verify_gate_list_red_with_claimed_tests(tmp_path, monkeypatch):
    repo = _list_repo(
        tmp_path, "listred",
        list_stdout="tests/t_test.py\n",
        list_stderr=(
            "run.sh: unregistered test-like file(s) in tests/ "
            "(no registry line claims them):\ntests/calc_test.go\n"
        ),
        list_rc=1,
    )
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    ok, failures, env_fail = stanok.verify_gate(_empty_plan())
    assert ok is False
    assert env_fail is False
    list_fails = [msg for name, msg in failures if name == "(list)"]
    assert len(list_fails) == 1
    assert "unregistered" in list_fails[0]


def test_verify_gate_list_red_empty_stdout(tmp_path, monkeypatch):
    repo = _list_repo(
        tmp_path, "listempty",
        list_stdout="",
        list_stderr="run.sh: no tests/ directory\n",
        list_rc=1,
    )
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    ok, failures, env_fail = stanok.verify_gate(_empty_plan())
    assert ok is False
    assert env_fail is False
    assert any(name == "(list)" and "no tests/ directory" in msg
               for name, msg in failures)


def test_verify_gate_list_green_no_tests(tmp_path, monkeypatch):
    repo = _list_repo(tmp_path, "listnone", list_stdout="", list_stderr="",
                      list_rc=0)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    ok, failures, env_fail = stanok.verify_gate(_empty_plan())
    assert ok is False
    assert env_fail is False
    assert any(name == "(no tests)" for name, _ in failures)


# --- 5: _contract_lock_forced_fail ---------------------------------------------

def test_contract_lock_forced_fail_triggers():
    job = {"contract_lock_violations": ["turn 1: MODIFIED: tests/t_test.py"]}
    assert stanok._contract_lock_forced_fail(job, 1) == 1
    assert job["verifier"] == "FAIL"
    assert "CONTRACT-LOCK" in job["error"]
    assert job["turns"] == 1
    assert any(name == "(contract_lock)"
               and "MODIFIED: tests/t_test.py" in msg
               for name, msg in job["failures"])


def test_contract_lock_forced_fail_clean():
    job = {"verifier": "PASS"}
    assert stanok._contract_lock_forced_fail(job, 2) is None
    assert job == {"verifier": "PASS"}
    job2 = {"contract_lock_violations": []}
    assert stanok._contract_lock_forced_fail(job2, 2) is None


# --- 6: _rotate_stale_summary ---------------------------------------------------

def test_rotate_stale_summary_rotates(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    ev = repo / "evidence" / "lbl"
    ev.mkdir(parents=True)
    (ev / "summary.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    stanok._rotate_stale_summary("lbl")
    assert not (ev / "summary.json").exists()
    assert (ev / "summary.json.prev").is_file()


def test_rotate_stale_summary_keeps_live_run(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    ev = repo / "evidence" / "lbl"
    ev.mkdir(parents=True)
    (ev / "summary.json").write_text("{}", encoding="utf-8")
    (ev / ".running").write_text("123", encoding="utf-8")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    stanok._rotate_stale_summary("lbl")
    assert (ev / "summary.json").is_file()
    assert not (ev / "summary.json.prev").exists()


def test_rotate_stale_summary_noop_when_absent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "evidence" / "lbl").mkdir(parents=True)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    stanok._rotate_stale_summary("lbl")
    ev = repo / "evidence" / "lbl"
    assert not (ev / "summary.json.prev").exists()


# --- 7: verify_gate suite mode (D4/CC-149) -------------------------------------

def _suite_repo(base: Path, name: str, all_rc: int, all_out: str,
                perfile_rc: int = 0) -> Path:
    """A tmp repo whose stub run.sh:
      - `list` prints tests/t_test.py and exits 0
      - `test --all` cats all.out and exits all_rc
      - `test <file>` (per-file fallback) exits perfile_rc
    """
    repo = base / name
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "tests" / "t_test.py").write_text("def test_x(): pass\n",
                                              encoding="utf-8")
    (repo / "all.out").write_text(all_out, encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "list" ]]; then echo "tests/t_test.py"; exit 0; fi\n'
        'if [[ "$1" == "test" && "$2" == "--all" ]]; then\n'
        "  cat all.out\n"
        f"  exit {all_rc}\n"
        "fi\n"
        f'if [[ "$1" == "test" ]]; then exit {perfile_rc}; fi\n'
        "exit 0\n",
    )
    return repo


def test_verify_gate_suite_pass(tmp_path, monkeypatch):
    repo = _suite_repo(tmp_path, "suitepass", all_rc=0, all_out="ok")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    ok, failures, env_fail = stanok.verify_gate(_empty_plan())
    assert ok is True
    assert failures == []
    assert env_fail is False


def test_verify_gate_suite_fail_rc1(tmp_path, monkeypatch):
    repo = _suite_repo(
        tmp_path, "suitefail", all_rc=1,
        all_out="=== tests/t_test.py ===\nFAILED tests/t_test.py::test_x")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    ok, failures, env_fail = stanok.verify_gate(_empty_plan())
    assert ok is False
    assert env_fail is False
    assert any(name == "(suite)" and "FAILED" in msg
               for name, msg in failures)


def test_verify_gate_suite_timeout_rc124(tmp_path, monkeypatch):
    repo = _suite_repo(tmp_path, "suitetimeout", all_rc=124, all_out="hung")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    ok, failures, env_fail = stanok.verify_gate(_empty_plan())
    assert ok is False
    assert env_fail is False
    assert any(name == "(suite)" and msg.startswith("TIMEOUT:")
               for name, msg in failures)


def test_verify_gate_suite_envfail_rc6(tmp_path, monkeypatch):
    repo = _suite_repo(tmp_path, "suiteenv", all_rc=6, all_out="runner missing")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    ok, failures, env_fail = stanok.verify_gate(_empty_plan())
    assert ok is False
    assert env_fail is True
    assert any(name == "(suite)" and msg.startswith("ENV-FAIL:")
               for name, msg in failures)


def test_verify_gate_suite_rc2_fallback_perfile(tmp_path, monkeypatch):
    # run.sh has no `--all` (rc=2) -> verify_gate falls back to per-file spawns
    # and attributes the failure to the file, not (suite).
    repo = _suite_repo(tmp_path, "suitefallback", all_rc=2, all_out="",
                       perfile_rc=1)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    ok, failures, env_fail = stanok.verify_gate(_empty_plan())
    assert ok is False
    assert env_fail is False
    assert any(name == "tests/t_test.py" for name, _ in failures)
    assert not any(name == "(suite)" for name, _ in failures)
