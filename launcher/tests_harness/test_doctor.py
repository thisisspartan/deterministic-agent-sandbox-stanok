"""doctor — structural invariants of the claude machine (R5: pytest port of hooks/doctor.sh).

Static invariants + mock runner launches (rc=15/20/22/20/24).
Count (do not hardcode the number in prose):
    uv run --directory <repo> pytest launcher/tests_harness --collect-only -q | tail -1
Run via hooks/doctor.sh (thin wrapper) or directly:
    .venv/bin/python -m pytest launcher/tests_harness/test_doctor.py -q

The mock launches run with STANOK_PY=system python3 (the SDK is imported
lazily, the gates are pure stdlib) and STANOK_NO_SANDBOX=1 (the tests check
the RUNNER, not the sandbox; the Docker container does not mount the host
/tmp, so mktemp /tmp/... tickets are invisible inside — rc=13).

Gate order (single source: launcher/stanok.py main()):
  label-guard (rc=15) -> ROLE-LEAK (rc=24) -> ticket (rc=13) ->
  dirty-tree (rc=22) -> lock (rc=21) -> [cmd_run: W2.1 ticket header
  (rc=13, no impl:/test:/docs:/reset:none) -> pre-flight /props (rc=20)]

Skip semantics (valid refusal, not a regression): rc=21 (a machine run is
in progress — lock held) / rc=22 (dirty tree fires before pre-flight).
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCH = REPO_ROOT / "launch.sh"
LOG_DIR = Path("/tmp/stanok-logs")
DEAD_SERVER = "http://127.0.0.1:59999"
MOCK_PORT = 59998


def _launch(args, env_extra):
    """Run launch.sh with the doctor env; return the exit code."""
    env = dict(os.environ)
    env["STANOK_PY"] = shutil.which("python3") or sys.executable
    env.update(env_extra)
    proc = subprocess.run(
        [str(LAUNCH)] + [str(a) for a in args],
        env=env, capture_output=True, timeout=120,
    )
    return proc.returncode


def _cleanup(label):
    shutil.rmtree(REPO_ROOT / "evidence" / label, ignore_errors=True)
    shutil.rmtree(LOG_DIR / label, ignore_errors=True)


def _ticket(tmp_path, body):
    t = tmp_path / f"doctor-ticket-{uuid.uuid4().hex[:8]}.md"
    t.write_text(body, encoding="utf-8")
    return t


# --- 1-10: static checks ----------------------------------------------------

def test_settings_exists():
    assert (REPO_ROOT / ".claude" / "settings.stanok.json").is_file()


def test_settings_valid_json():
    json.load(open(REPO_ROOT / ".claude" / "settings.stanok.json"))


def test_verifier_hook_in_process():
    src = (REPO_ROOT / "launcher" / "stanok.py").read_text(encoding="utf-8")
    assert "_verifier_hook" in src


def test_claude_md_exists():
    assert (REPO_ROOT / "CLAUDE.md").is_file()


def test_write_paths_exist():
    for d in ("src", "tests", "docs", "scripts"):
        assert (REPO_ROOT / d).is_dir(), d


def test_git_repo_initialized():
    assert (REPO_ROOT / ".git").exists()


def test_docker_available():
    assert shutil.which("docker") is not None


def test_machine_image_built():
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    assert subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True
    ).returncode == 0


def test_docker_image_digest_matches():
    # CC-106: the image digest/runner preflight moved from the launch path
    # (former blocking rc=25) to doctor. Import and call the SAME
    # preflight_image the launcher uses — no second shell implementation.
    sys.path.insert(0, str(REPO_ROOT / "launcher"))
    import stanok
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    assert stanok.preflight_image(image), \
        "image preflight failed: digest mismatch or runner unavailable"


def test_contract_lock_runsh():
    # P2: scripts/run.sh is under contract_lock unless the ticket declares it
    # (runner-update ticket) or it did not exist at start (bootstrap).
    # Unit-level: snapshot the manifest, modify run.sh, expect a violation;
    # with mutable_paths=("scripts/run.sh",) — no violation.
    sys.path.insert(0, str(REPO_ROOT / "launcher"))
    import stanok
    runsh = REPO_ROOT / "scripts" / "run.sh"
    assert runsh.is_file()
    orig = runsh.read_text(encoding="utf-8")
    before = stanok._tests_manifest()
    assert "scripts/run.sh" in before
    try:
        runsh.write_text(orig + "# contract-lock probe\n", encoding="utf-8")
        job = {}
        plan = stanok.SessionPlan(
            declared_paths=(), mutable_paths=(),
            protected_paths=tuple(before.keys()),
            rw_zones=stanok.sandbox.DEFAULT_RW_ZONES, probe_specs=())
        stanok._check_contract_lock(before, job, 1, plan)
        assert any("scripts/run.sh" in v
                   for v in job.get("contract_lock_violations", [])), \
            f"undeclared run.sh modification not flagged: {job}"
        job2 = {}
        plan2 = stanok.SessionPlan(
            declared_paths=("scripts/run.sh",), mutable_paths=("scripts/run.sh",),
            protected_paths=tuple(before.keys()),
            rw_zones=stanok.sandbox.DEFAULT_RW_ZONES, probe_specs=())
        stanok._check_contract_lock(before, job2, 1, plan2)
        assert not job2.get("contract_lock_violations"), \
            f"declared run.sh modification wrongly flagged: {job2}"
    finally:
        runsh.write_text(orig, encoding="utf-8")


def test_manifest_skips_pycache():
    # w12-verify: .pyc cache artifacts must not enter the contract_lock
    # manifest — a routine `rm -rf __pycache__` is not a DELETED violation.
    sys.path.insert(0, str(REPO_ROOT / "launcher"))
    import stanok
    pycache = REPO_ROOT / "tests" / "__pycache__"
    pycache.mkdir(exist_ok=True)
    probe = pycache / "probe_test.cpython-311.pyc"
    probe.write_bytes(b"probe")
    try:
        manifest = stanok._tests_manifest()
        assert not any("__pycache__" in k for k in manifest), \
            f"__pycache__ leaked into the manifest: " \
            f"{sorted(k for k in manifest if '__pycache__' in k)}"
    finally:
        probe.unlink(missing_ok=True)


def test_claude_md_matches_registry():
    # W5: CLAUDE.md "Test forms" must name every stack in the run.sh registry
    # (extension + a runner word). A new registry line without a CLAUDE.md edit
    # drops this test.
    import re
    runsh = (REPO_ROOT / "scripts" / "run.sh").read_text(encoding="utf-8")
    m = re.search(r"STACKS='(.*?)'", runsh, re.S)
    assert m, "STACKS registry not found in scripts/run.sh"
    stacks = [ln for ln in m.group(1).splitlines() if ln.strip()]
    assert stacks, "empty STACKS registry"
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    tf = re.search(r"## Test forms.*?(?=\n## |\Z)", claude, re.S)
    assert tf, "CLAUDE.md missing '## Test forms' section"
    tf_text = tf.group(0)
    stop = {"uv", "run", "python3", "bash", "sh", "timeout", "m", "no", "project", "q", "p", "o"}
    for ln in stacks:
        fields = ln.split("|")
        assert len(fields) >= 4, f"malformed registry line: {ln!r}"
        ext, test_runner = fields[0], fields[3]
        # (a) the extension must be a named stack label in Test forms
        assert re.search(r"\*\*" + re.escape(ext) + r"\*\*", tf_text), \
            f"CLAUDE.md Test forms missing stack label **{ext}** (registry line: {ln!r})"
        # (b) a runner word from the registry's test-runner must appear in Test forms
        runner_tokens = {t for t in re.findall(r"[A-Za-z][A-Za-z0-9]*", test_runner) if t not in stop}
        tf_tokens = {t for t in re.findall(r"[A-Za-z][A-Za-z0-9]*", tf_text)}
        assert runner_tokens & tf_tokens, \
            f"CLAUDE.md Test forms names no runner word for **{ext}** (runner: {test_runner!r})"


# --- 12-16: mock runner launches --------------------------------------------

def test_runner_label_guard(tmp_path):
    # A label starting with '--' -> rc=15 BEFORE ticket resolution.
    # The ticket EXISTS so rc=13 is not masked when the label-guard is absent.
    t = _ticket(tmp_path, "# doctor\n\nplaceholder\n")
    rc = _launch(["run", t, "--", "--background"],
                 {"STANOK_SERVER_URL": DEAD_SERVER, "STANOK_NO_SANDBOX": "1"})
    assert rc == 15, f"expected rc=15, got rc={rc}"


def test_runner_fail_fast(tmp_path):
    # A dead server -> rc=20. The ticket carries `reset: none` so the W2.1
    # header check (rc=13) does not mask the pre-flight refusal.
    t = _ticket(tmp_path, "# doctor\n\nreset: none\n")
    label = f"doctor-dead-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    try:
        rc = _launch(["run", t, label],
                     {"STANOK_SERVER_URL": DEAD_SERVER, "STANOK_NO_SANDBOX": "1"})
    finally:
        _cleanup(label)
    if rc == 21:
        pytest.skip("a machine run is in progress — lock is held")
    if rc == 22:
        pytest.skip("dirty tree — dirty-tree rc=22 before pre-flight")
    assert rc == 20, f"expected rc=20, got rc={rc}"


def test_runner_dirty_tree(tmp_path):
    # An uncommitted file in the repo -> rc=22 (fail-closed before pre-flight).
    marker = REPO_ROOT / ".doctor-dirty-marker"
    t = _ticket(tmp_path, "# doctor\n\nplaceholder\n")
    label = f"doctor-dirty-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    marker.write_text("marker\n", encoding="utf-8")
    try:
        rc = _launch(["run", t, label],
                     {"STANOK_SERVER_URL": DEAD_SERVER, "STANOK_NO_SANDBOX": "1"})
    finally:
        marker.unlink(missing_ok=True)
        _cleanup(label)
    assert rc == 22, f"expected rc=22, got rc={rc}"


class _SmallCtxHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"default_generation_settings": {"n_ctx": 4096}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def mock_small_server():
    server = HTTPServer(("127.0.0.1", MOCK_PORT), _SmallCtxHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{MOCK_PORT}"
    server.shutdown()


def test_runner_preflight_window(tmp_path, mock_small_server):
    # A LIVE server whose n_ctx is below the required window
    # (STANOK_REQUIRED_WINDOW — the window moved from settings.env to env) -> rc=20.
    t = _ticket(tmp_path, "# doctor\n\nreset: none\n")
    label = f"doctor-window-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    try:
        rc = _launch(["run", t, label],
                     {"STANOK_SERVER_URL": mock_small_server, "STANOK_NO_SANDBOX": "1",
                      "STANOK_REQUIRED_WINDOW": "128000"})
    finally:
        _cleanup(label)
    if rc == 21:
        pytest.skip("a machine run is in progress — lock is held")
    if rc == 22:
        pytest.skip("dirty tree — dirty-tree rc=22 before pre-flight")
    assert rc == 20, f"expected rc=20, got rc={rc}"


def test_runner_role_leak(tmp_path):
    # A CLAUDE.md above the repo -> rc=24 (fail-closed, no side effects).
    # The temp repo is git-init'ed so the dirty-tree gate (rc=22) does not
    # fire before the role-leak gate on a non-git directory.
    root = tmp_path / "roleleak"
    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (root / "CLAUDE.md").touch()
    t = _ticket(tmp_path, "# doctor\n\nplaceholder\n")
    label = f"doctor-roleleak-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    rc = _launch(["run", t, label],
                 {"STANOK_REPO": str(repo),
                  "STANOK_SERVER_URL": DEAD_SERVER,
                  "STANOK_NO_SANDBOX": "1"})
    assert rc == 24, f"expected rc=24, got rc={rc}"
