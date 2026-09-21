"""Acceptance contract for the py stack of scripts/run.sh (hermetic: tmp repo + live run.sh).

Pins what a Python-stack ticket experiences through `run.sh test`:
  I1  a CORRECT implementation passes for every natural import style
      (`from src import x`, `sys.path.insert(...)`, bare `import x`)
  I2  a RED test that imports a not-yet-written module is a FAILED test (rc=1),
      never rc=2 (rc=2 = run.sh refused the path; the verifier hook is silent on it)
  I3  ordinary red -> 1, green -> 0, missing path -> 2 (refusal keeps its own code)
  I4  a script-style file (module-level assert, no test functions) is NOT a pass
Run: <venv>/bin/python -m pytest launcher/tests_harness/test_runsh_py_stack.py -q
"""
import os, shutil, subprocess, sys
from pathlib import Path
import pytest

RUNSH = Path(os.environ.get("RUNSH_UNDER_TEST", Path(__file__).resolve().parents[2] / "scripts" / "run.sh"))

@pytest.fixture()
def repo(tmp_path):
    for d in ("scripts", "tests", "src"):
        (tmp_path / d).mkdir()
    shutil.copy(RUNSH, tmp_path / "scripts" / "run.sh")
    (tmp_path / "src" / "fire.py").write_text("def f():\n    return 1\n")   # a CORRECT implementation
    return tmp_path

def run(repo, rel):
    env = dict(os.environ, VIRTUAL_ENV=os.path.dirname(os.path.dirname(sys.executable)))  # same trick as test_runsh_contract
    return subprocess.run(["bash", "scripts/run.sh", "test", rel], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)

STYLES = {
    "from-src":  "from src import fire\n\ndef test_a():\n    assert fire.f() == 1\n",
    "sys-path":  "import os, sys\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\nimport fire\n\ndef test_b():\n    assert fire.f() == 1\n",
    "bare":      "import fire\n\ndef test_c():\n    assert fire.f() == 1\n",
}

@pytest.mark.parametrize("style", STYLES)
def test_I1_correct_implementation_passes_for_every_import_style(repo, style):
    (repo / "tests" / f"{style.replace('-', '')}_test.py").write_text(STYLES[style])
    p = run(repo, f"tests/{style.replace('-', '')}_test.py")
    assert p.returncode == 0, p.stdout + p.stderr

def test_I2_red_by_missing_module_is_rc1_not_rc2(repo):
    (repo / "tests" / "miss_test.py").write_text("from src import not_written_yet\n\ndef test_x():\n    pass\n")
    assert run(repo, "tests/miss_test.py").returncode == 1

def test_I3_ordinary_codes(repo):
    (repo / "tests" / "ok_test.py").write_text("def test_ok():\n    assert True\n")
    (repo / "tests" / "bad_test.py").write_text("def test_bad():\n    assert 1 == 2\n")
    assert run(repo, "tests/ok_test.py").returncode == 0
    assert run(repo, "tests/bad_test.py").returncode == 1
    assert run(repo, "tests/nope_test.py").returncode == 2          # refusal keeps rc=2

def test_I4_script_style_is_not_a_pass(repo):
    (repo / "tests" / "script_test.py").write_text("assert 1 == 1\n")
    assert run(repo, "tests/script_test.py").returncode != 0
