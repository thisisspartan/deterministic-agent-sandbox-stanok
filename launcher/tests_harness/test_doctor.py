"""doctor — structural invariants of the claude machine (R5: pytest port of hooks/doctor.sh).

Static invariants + mock runner launches (rc=15/20/22/20/24).
CC-231 (production cutover): k8s runtime health — kubectl on PATH, a Ready
node (the template securityContext checks live in test_k8s_manifests.py).
Count (do not hardcode the number in prose):
    uv run --directory <repo> pytest launcher/tests_harness --collect-only -q | tail -1
Run via hooks/doctor.sh (thin wrapper) or directly:
    .venv/bin/python -m pytest launcher/tests_harness/test_doctor.py -q

The mock launches run with STANOK_PY=system python3 (the SDK is imported
lazily, the gates are pure stdlib) and STANOK_NO_SANDBOX=1 (the no-sandbox
test mode: the CLI runs the gates in-process on the host instead of
dispatching to k8s — the tmp tickets/workspaces the tests build are host
paths the cluster never sees).

Gate order (single source: launcher/cli.py _launch_gates):
  label-guard (rc=15) -> ROLE-LEAK (rc=24) -> ticket (rc=13) ->
  dirty-tree (rc=22) -> hidden-files (rc=26) -> test-config (rc=27) ->
  lock (rc=21) -> [cmd_run: W2.1 ticket header
  (rc=13: no impl:/test:/docs:/reset:none, or a create-declared path that
  already exists) -> pre-flight /props (rc=20)]
Precedence is pinned by test_runner_gate_precedence_* (two violations at
once -> the earlier gate's rc wins).

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

from conftest import VENV_BIN  # interpreter pin, same as the run.sh suites (CC-156)
from launcher import gates, verify
from launcher.config import Config
from launcher.plan import SessionPlan

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCH = REPO_ROOT / "launch.sh"
LOG_DIR = Path("/tmp/stanok-logs")
DEAD_SERVER = "http://127.0.0.1:59999"
MOCK_PORT = 59998

# CI bare-environment skip guards (SPEC-CI-MINIMAL, 2026-10-13): the harness
# must run green in a bare checkout (CI: no docker daemon/image, no jq, no
# k8s cluster). Environment-dependent probes SKIP with an explicit reason —
# they are valid refusals, not regressions (same semantics as the rc=21/22
# skips above). The CI workflow asserts the exact skip count; if a tool
# appears on PATH its skip turns back into a real test and the count check
# fails — the guards cannot rot silently.
_NO_DOCKER = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker CLI not on PATH (bare environment) — image probes not applicable",
)


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


def test_settings_deny_surface():
    # Operator decision 2026-10-15 (audit line "subagent ban is only absence
    # from allow"): the ban is made EXPLICIT — "Agent" is denied; protected
    # dirs are denied for ALL write tools (the old set had Read/Edit only:
    # deny Edit(path) does NOT block Write(path)). The tool surface itself is
    # already restricted by session._agent_options tools=cfg.curated_tools
    # (R3) — this deny is the explicit defense-in-depth layer.
    data = json.load(open(REPO_ROOT / ".claude" / "settings.stanok.json"))
    deny = set(data["permissions"]["deny"])
    assert "Agent" in deny
    for d in (".git", "hooks", "launcher", ".claude", "evidence"):
        for tool in ("Read", "Edit", "Write"):
            assert f"{tool}({d}/**)" in deny, f"missing deny: {tool}({d}/**)"


def test_verifier_hook_in_process():
    # The hook is launcher code (session.py since the PLAN-HYGIENE split), not
    # an external hook script — pinned at its real home.
    src = (REPO_ROOT / "launcher" / "session.py").read_text(encoding="utf-8")
    assert "_verifier_hook" in src


def test_claude_md_exists():
    assert (REPO_ROOT / "CLAUDE.md").is_file()


def test_write_paths_exist():
    for d in ("src", "tests", "docs", "scripts"):
        assert (REPO_ROOT / d).is_dir(), d


def test_git_repo_initialized():
    assert (REPO_ROOT / ".git").exists()


# --- Trusted fixtures (boundary oracles): incident 7fb18e6 -------------------
# 7fb18e6 "chore: clean for new task — infra only" deleted 12 files/2505
# lines from a clean tree, including the boundary-judge pair
# (tests/fixtures/vt_screen.py + tests/vt_screen_test.py). No gate could
# see it: the two-echelon protection fires on MACHINE patches inside a turn
# (verify.py manifest diff; verify.py:305) and the host has no turn. A
# HEAD-anchored check does not help either — once the deletion is committed,
# HEAD matches the tree and the check greens again. Operator decision
# 2026-10-18 ("option (a) plus manifest-check"): trusted helpers stay in
# tests/fixtures and are declared in this check. Removal is possible only by
# editing TRUSTED_FIXTURES here — an explicit, reviewable host-side diff.

# The manifest of trusted fixture modules (repo-relative). A fixture is
# trusted infrastructure (an accept oracle), not product: cleanup sweeps
# that remove product files must not remove these.
TRUSTED_FIXTURES = ("tests/fixtures/vt_screen.py",)


def _fixture_selftests(fixture_rel):
    """Self-tests that prove one fixture: tests/**/<stem>_test.py.

    tests/fixtures/ itself is excluded: fixtures are the trusted side, not
    checks (the same exemption run.sh applies in test discovery,
    scripts/run.sh:120,129, and CLAUDE.md's W12 exemptions).
    """
    tests_dir = REPO_ROOT / "tests"
    stem = Path(fixture_rel).stem
    out = []
    if not tests_dir.is_dir():
        return out
    for p in tests_dir.rglob(f"{stem}_test.py"):
        if "fixtures" in p.relative_to(tests_dir).parts:
            continue
        out.append(p)
    return out


def _all_fixtures_on_disk():
    fx = REPO_ROOT / "tests" / "fixtures"
    if not fx.is_dir():
        return []
    return sorted(str(p.relative_to(REPO_ROOT)) for p in fx.rglob("*.py"))


def test_trusted_fixtures_present_and_paired():
    # (1) every declared trusted fixture exists on disk; (2) every fixture
    # on disk — declared or not — has a pairing self-test. (1) guards the
    # trusted set against silent deletion (the 7fb18e6 class); (2) makes
    # "trusted" mean testable, not just present.
    missing = [f for f in TRUSTED_FIXTURES if not (REPO_ROOT / f).is_file()]
    assert not missing, (
        f"trusted fixtures missing from the working tree: {missing} — "
        "host-side cleanup never passes any pipeline gate (no gate sees a "
        "host action); this check IS the gate. Restore the files, or edit "
        "TRUSTED_FIXTURES deliberately (a host-side diff, reviewable).")
    unpaired = [f for f in sorted(set(TRUSTED_FIXTURES) | set(_all_fixtures_on_disk()))
                if not _fixture_selftests(f)]
    assert not unpaired, (
        f"fixtures without a pairing self-test (tests/**/<stem>_test.py): "
        f"{unpaired} — a fixture nobody tests is not a trusted helper")


def test_trusted_fixture_selftests_green():
    # Existence is not trust: each pairing self-test must actually run
    # green. Subprocess isolation on purpose — the judge's own suite opens
    # real PTYs and must be executed the way run.sh's py runner executes
    # them: the image-pinned interpreter (conftest.VENV_BIN, CC-156) when
    # .venv is present, otherwise the harness's own interpreter — the same
    # convention as conftest's run() helper. run.sh's two hygiene flags
    # (-p no:cacheprovider, PYTHONDONTWRITEBYTECODE) are carried over so a
    # doctor probe cannot dirty the tree it guards. The bound is looser than
    # run.sh's per-file 60 s (scripts/run.sh:199): this guard invokes a
    # whole suite once and is capped by subprocess.run's timeout.
    targets = sorted({t for f in TRUSTED_FIXTURES
                      for t in _fixture_selftests(f)})
    assert targets, "no pairing self-tests found for TRUSTED_FIXTURES"
    for t in targets:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if VENV_BIN.is_dir():
            env["PATH"] = str(VENV_BIN) + os.pathsep + env.get("PATH", "")
        proc = subprocess.run(
            ["python3", "-m", "pytest", "-p", "no:cacheprovider", "-q",
             str(t.relative_to(REPO_ROOT))],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
            timeout=180,
        )
        assert proc.returncode == 0, (
            f"trusted-fixture self-test {t.relative_to(REPO_ROOT)} is not "
            f"green (rc={proc.returncode}):\n"
            f"{(proc.stdout + proc.stderr)[-1500:]}")


@_NO_DOCKER
def test_docker_available():
    assert shutil.which("docker") is not None


@_NO_DOCKER
def test_machine_image_built():
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    assert subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True
    ).returncode == 0


@_NO_DOCKER
def test_docker_image_digest_matches():
    # CC-106: the image digest/runner preflight moved from the launch path
    # (former blocking rc=25) to doctor. Import and call the SAME
    # preflight_image the launcher uses — no second shell implementation.
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    assert gates.preflight_image(Config(), image), \
        "image preflight failed: digest mismatch or runner unavailable"


@_NO_DOCKER
def test_image_cli_version_matches_packaged_version():
    # SPEC-DOCTOR-CLI-VERSION-2026-10-22 (R4 intent closed, operator order
    # 2026-10-22): the binary reachable as `claude` in the built image must
    # RUN (I1) and name the version declared by the package.json next to
    # that same binary (I2). The package.json path is resolved INSIDE the
    # image from the claude executable itself (readlink) — no version
    # literal and no /opt path here (canonical source: the packaged
    # manifest, operator decision 2026-10-22). Scope, stated openly: this
    # gates image-internal consistency and a runnable claude binary; the
    # absolute version pin stays enforced by the setup.sh/Dockerfile SHA
    # gates and the stanok.digest label (test_docker_image_digest_matches).
    import re
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")

    def _probe(*argv):
        # No ENTRYPOINT/CMD in the image (Dockerfile: deliberate) — the
        # full command is passed, same pattern as gates.preflight_image.
        p = subprocess.run(["docker", "run", "--rm", image, *argv],
                           capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, (
            f"docker run --rm {image} {argv[0]}... rc={p.returncode}: "
            f"{(p.stdout + p.stderr)[-400:]}")
        return p.stdout

    reported = re.search(r"\d+\.\d+\.\d+", _probe("claude", "--version"))
    assert reported, "claude --version printed no version token (I1)"
    packaged = _probe("/bin/sh", "-c",
                      'bin=$(readlink -f "$(command -v claude)"); '
                      'node -e "console.log(require(process.argv[1]).version)" '
                      '"$(dirname "$bin")/package.json"').strip()
    assert packaged == reported.group(), (
        f"image-internal version mismatch (I2): claude reports "
        f"{reported.group()!r} but its packaged package.json declares "
        f"{packaged!r}")


# --- CC-231 (production cutover): k8s is the DEFAULT runtime ---------------
# The worker/fresh template securityContext validation is NOT duplicated
# here — it is pinned in test_k8s_manifests.py (primitive-first: one home
# per invariant). These two checks cover the HOST side of the default path:
# the kubectl CLI and a Ready node.

def _supervisor_zone_present():
    return (REPO_ROOT.parent / "CONTEXT.md").is_file()


def test_kubectl_available():
    # The default runtime needs the kubectl CLI on the host. Public clone
    # (no supervisor zone): skip — valid absence (same pattern as
    # test_context_md_budget).
    if not _supervisor_zone_present():
        pytest.skip("supervisor zone not present (public clone) — "
                    "k8s runtime not expected")
    if shutil.which("kubectl") is None:
        # CI bare-environment skip guard (SPEC-CI-MINIMAL): no kubectl on
        # PATH -> the k8s runtime is not expected here; the absence is
        # flagged by the skip reason, not by a failure.
        pytest.skip("kubectl not on PATH (bare environment) — "
                    "k8s runtime not expected")


def test_k8s_cluster_nodes_ready():
    # The node serving the worker/fresh Jobs must be Ready.
    if not _supervisor_zone_present():
        pytest.skip("supervisor zone not present (public clone) — "
                    "k8s runtime not expected")
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl unavailable — flagged by test_kubectl_available")
    # Same kubeconfig resolution as the launch path (kube._cluster_env,
    # CC-232): the default /etc/rancher/k3s/k3s.yaml is not user-readable —
    # fall back to ~/.kube/config when KUBECONFIG is unset (the operator
    # host layout).
    env = dict(os.environ)
    kc = Path.home() / ".kube" / "config"
    if not env.get("KUBECONFIG") and kc.is_file():
        env["KUBECONFIG"] = str(kc)
    out = subprocess.run(["kubectl", "get", "nodes", "--no-headers"],
                         env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f"kubectl get nodes failed: {out.stderr}"
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    assert lines, "kubectl returned no nodes"
    for ln in lines:
        fields = ln.split()
        # columns: NAME STATUS ROLES AGE VERSION — STATUS is 2nd; exact
        # match: "NotReady" CONTAINS "Ready" — a substring test is a false
        # green (same fix as the CC-232 pre-flight gate).
        assert fields[1] == "Ready", f"node not Ready: {ln}"


def test_contract_lock_runsh():
    # P2: scripts/run.sh is under contract_lock unless the ticket declares it
    # (runner-update ticket) or it did not exist at start (bootstrap).
    # Unit-level: snapshot the manifest, modify run.sh, expect a violation;
    # with declared_paths=("scripts/run.sh",) — no violation.
    cfg = Config()
    runsh = REPO_ROOT / "scripts" / "run.sh"
    assert runsh.is_file()
    orig = runsh.read_text(encoding="utf-8")
    before = verify._tests_manifest(cfg)
    assert "scripts/run.sh" in before
    try:
        runsh.write_text(orig + "# contract-lock probe\n", encoding="utf-8")
        job = {}
        plan = SessionPlan(declared_paths=())
        verify._check_contract_lock(cfg, before, job, 1, plan)
        assert any("scripts/run.sh" in v
                   for v in job.get("contract_lock_violations", [])), \
            f"undeclared run.sh modification not flagged: {job}"
        job2 = {}
        plan2 = SessionPlan(declared_paths=("scripts/run.sh",))
        verify._check_contract_lock(cfg, before, job2, 1, plan2)
        assert not job2.get("contract_lock_violations"), \
            f"declared run.sh modification wrongly flagged: {job2}"
    finally:
        runsh.write_text(orig, encoding="utf-8")


def test_manifest_skips_pycache():
    # w12-verify: .pyc cache artifacts must not enter the contract_lock
    # manifest — a routine `rm -rf __pycache__` is not a DELETED violation.
    pycache = REPO_ROOT / "tests" / "__pycache__"
    pycache.mkdir(exist_ok=True)
    probe = pycache / "probe_test.cpython-311.pyc"
    probe.write_bytes(b"probe")
    try:
        manifest = verify._tests_manifest(Config())
        assert not any("__pycache__" in k for k in manifest), \
            f"__pycache__ leaked into the manifest: " \
            f"{sorted(k for k in manifest if '__pycache__' in k)}"
    finally:
        probe.unlink(missing_ok=True)


def _registry_lines():
    """The live STACKS registry as a list of field lists.

    CC-168: the manifests (scripts/stacks/*.toml, sorted by filename) are
    the single source of truth — parse them with tomllib, the same parser
    run.sh and launcher/gates.py use (no generated file to go stale).
    """
    import tomllib
    stacks = REPO_ROOT / "scripts" / "stacks"
    keys = ("ext", "test_glob", "name_regex",
            "test_runner", "smoke_runner", "preflight")
    lines = []
    for name in sorted(os.listdir(stacks)):
        if not name.endswith(".toml"):
            continue
        with open(stacks / name, "rb") as f:
            m = tomllib.load(f)
        lines.append([m[k] for k in keys])
    assert lines, "no stack manifests in scripts/stacks/"
    return lines


def test_registry_shape():
    # CC-147: the registry line format is exactly 6 fields
    # (ext|test-glob|name-regex|test-runner|smoke-runner|preflight).
    for fields in _registry_lines():
        assert len(fields) == 6, f"registry line must have 6 fields, got {len(fields)}: {fields!r}"


def test_context_md_budget():
    # CC-146: the live CONTEXT.md (parent repo, read at every supervisor
    # session start) must stay under the ~16 KB budget; closed waves go to
    # specs/ARCHIVE/CONTEXT-<wave>.md. Whether the supervisor-zone files are
    # PUBLISHED at all is pinned by test_supervisor_zone_not_published.
    ctx = REPO_ROOT.parent / "CONTEXT.md"
    if not ctx.is_file():
        # The public clone has no supervisor zone: CONTEXT.md is a session log
        # (project history), gitignored local-only state — valid absence.
        pytest.skip("supervisor zone not present — CONTEXT.md absent (public clone)")
    size = ctx.stat().st_size
    assert size <= 16384, \
        f"CONTEXT.md is {size} bytes (> 16384 budget) — archive closed waves " \
        f"to specs/ARCHIVE/CONTEXT-<wave>.md"


def _parent_repo_state():
    """State of the supervisor-zone parent (REPO_ROOT.parent):
    "present" | "absent" | "not-parent".

    Authenticity: the parent must be a git repo whose .gitmodules names the
    `stanok` submodule — the published-parent layout. Without this check the
    guard passes VACUOUSLY outside that layout: `git ls-files` in a non-repo
    returns rc=128 with EMPTY stdout, so `assert not tracked` is green while
    having checked nothing (operator-found defect, 2026-10-13).
    """
    parent = REPO_ROOT.parent
    rc = subprocess.run(["git", "-C", str(parent), "rev-parse", "--git-dir"],
                        capture_output=True, text=True).returncode
    if rc != 0:
        return "absent"
    gm = parent / ".gitmodules"
    if not gm.is_file() or "stanok" not in gm.read_text(encoding="utf-8"):
        return "not-parent"
    return "present"


def test_supervisor_zone_not_published():
    # The parent repo is published (main -> github). Supervisor-zone state
    # files (CONTEXT.md, specs/STATUS.md, specs/RISK-ACCEPTANCES.md), their
    # archives (specs/ARCHIVE/*), analysis records (specs/ANALYSIS-*.md),
    # the tickets (tickets/ — private by operator decision 2026-10-13; the
    # machine reads them from the supervisor's local directory) and the live
    # .mcp.json (external review 2026-10-16: machine-local absolute paths;
    # the published template is .mcp.json.example) carry internal
    # addresses/hosts and incident history — they must NEVER be tracked there
    # (rule: the parent .gitignore — publication is direct push of the tracked
    # tree, the sync-skeleton mirror was retired 2026-10-21; enforced here).
    # A tracked path is a published path; present-but-UNTRACKED (the
    # supervisor's local zone, gitignored) is the valid state.
    # Layout rules (SPEC-CI-MINIMAL, 2026-10-13): the guard is meaningful
    # ONLY in the published-parent layout (CI checks out the parent with the
    # stanok submodule -> state "present" -> the guard RUNS). Outside it:
    # skip with an explicit reason (standalone stanok checkout), never a
    # vacuous pass. Inside the layout a failing `git ls-files` is a FAIL,
    # not an empty list.
    state = _parent_repo_state()
    if state == "absent":
        pytest.skip("no parent repo at REPO_ROOT.parent (standalone stanok "
                    "checkout) — guard applies to the published parent only")
    if state == "not-parent":
        pytest.skip(f"REPO_ROOT.parent ({REPO_ROOT.parent}) is a git repo "
                    "without a `stanok` submodule in .gitmodules — not this "
                    "project's parent; guard applies to the published parent only")
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT.parent), "ls-files",
         "CONTEXT.md", "specs/STATUS.md", "specs/RISK-ACCEPTANCES.md",
         "specs/ARCHIVE", "specs/ANALYSIS-*.md", "tickets", ".mcp.json"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        pytest.fail(f"git ls-files in the parent failed (rc={out.returncode}): "
                    f"{out.stderr.strip()} — the guard must not pass vacuously")
    tracked = [ln for ln in out.stdout.splitlines() if ln.strip()]
    assert not tracked, (
        f"supervisor-zone files tracked in the parent repo (would be "
        f"published): {tracked} — they must stay gitignored (local-only zone)"
    )


def test_ci_workflow_sha_pinned_and_least_privilege():
    # External review 2026-10-16: third-party action refs must be full commit
    # SHAs (a tag is movable, a SHA is not) and the workflow must declare
    # least-privilege permissions (contents: read only). Guarded in the
    # published-parent layout only (the workflow lives in the parent; CI runs
    # it there) — outside it, skip, never a vacuous pass.
    state = _parent_repo_state()
    if state != "present":
        pytest.skip(f"parent layout state {state!r} — the CI workflow guard "
                    "applies to the published parent only")
    wf = REPO_ROOT.parent / ".github" / "workflows" / "harness.yml"
    if not wf.is_file():
        pytest.fail("published parent has no .github/workflows/harness.yml — "
                    "the harness CI contract is published, its absence is a defect")
    text = wf.read_text(encoding="utf-8")
    import re
    for ref in re.findall(r"^\s*uses:\s*(\S+)", text, re.M):
        org = ref.split("@", 1)[0]
        if org.startswith("actions/"):
            sha = ref.split("@", 1)[1] if "@" in ref else ""
            assert re.fullmatch(r"[0-9a-f]{40}", sha), (
                f"CI action {ref!r} is not pinned to a full commit SHA — "
                "resolve the tag via git ls-remote and pin the SHA")
    assert re.search(r"^permissions:\n(?:[ \t]+\S+[^\n]*\n)*", text, re.M), \
        "workflow has no top-level permissions: block"
    perms_block = re.search(r"^permissions:\n((?:[ \t]+\S+[^\n]*\n)*)", text, re.M).group(1)
    scopes = re.findall(r"([a-z-]+):\s*(\S+)", perms_block)
    assert scopes and all(s == ("contents", "read") for s in scopes), \
        f"permissions must be exactly contents: read, got {scopes}"


def test_claude_md_matches_registry():
    # W5: CLAUDE.md "Test forms" must name every stack in the run.sh registry
    # (extension + a runner word). A new registry line without a CLAUDE.md edit
    # drops this test.
    import re
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    tf = re.search(r"## Test forms.*?(?=\n## |\Z)", claude, re.S)
    assert tf, "CLAUDE.md missing '## Test forms' section"
    tf_text = tf.group(0)
    stop = {"uv", "run", "python3", "bash", "sh", "timeout", "m", "no", "project", "q", "p", "o"}
    for fields in _registry_lines():
        ext, test_runner = fields[0], fields[3]
        # (a) the extension must be a named stack label in Test forms
        assert re.search(r"\*\*" + re.escape(ext) + r"\*\*", tf_text), \
            f"CLAUDE.md Test forms missing stack label **{ext}** (registry line: {fields!r})"
        # (b) a runner word from the registry's test-runner must appear in Test forms
        runner_tokens = {t for t in re.findall(r"[A-Za-z][A-Za-z0-9]*", test_runner) if t not in stop}
        tf_tokens = {t for t in re.findall(r"[A-Za-z][A-Za-z0-9]*", tf_text)}
        assert runner_tokens & tf_tokens, \
            f"CLAUDE.md Test forms names no runner word for **{ext}** (runner: {test_runner!r})"


def test_stacks_md_matches_registry():
    # CC-147: specs/STACKS.md documents the registry — its "Current registry"
    # block must contain exactly the live registry lines (order-insensitive
    # since CC-148: the generator emits manifest sort order), and its format
    # line must list all 6 field names.
    import re
    stacks_md = REPO_ROOT.parent / "specs" / "STACKS.md"
    if not stacks_md.is_file():
        # specs/STACKS.md lives in the published parent (tracked there).
        # Outside the parent layout (standalone stanok checkout) the doc is
        # absent — skip with a reason, not a FileNotFoundError crash.
        pytest.skip("specs/STACKS.md absent (no parent layout) — registry doc "
                    "check applies to the published parent only")
    text = stacks_md.read_text(encoding="utf-8")
    blocks = re.findall(r"```\n(.*?)\n```", text, re.S)
    assert blocks, "specs/STACKS.md missing code blocks"
    doc_lines = [ln for ln in blocks[-1].splitlines() if ln.strip()]
    reg_lines = ["|".join(f) for f in _registry_lines()]
    assert sorted(doc_lines) == sorted(reg_lines), \
        f"specs/STACKS.md registry block drifted from the live registry:\n" \
        f"  doc: {sorted(doc_lines)}\n  registry: {sorted(reg_lines)}"
    fmt = re.search(r"<ext>\|<test-glob>\|<name-regex>\|<test-runner>\|<smoke-runner>(\|<preflight>)?", text)
    assert fmt and fmt.group(1), \
        "specs/STACKS.md format line must document all 6 fields incl. <preflight>"


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


def test_runner_stale_create_rc13(tmp_path):
    # CC-133, end to end through main(): the CC-119 fire16 retry1 shape — an
    # EXISTING test declared as a create — is refused rc=13 in cmd_run, after
    # the gates but BEFORE the pre-flight (a dead server would give rc=20) and
    # before any container or agent starts. The quarantine -> contract-lock
    # DENY -> 1800 s watchdog loop therefore cannot happen anymore.
    # A private git-init'ed repo keeps this independent of the live tree's
    # cleanliness (the temp repo is committed, so rc=22 does not fire).
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "fire_color16_test.py").write_text(
        "def test_x():\n    assert 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-c", "user.email=doctor@stanok", "-c", "user.name=doctor",
                    "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    t = _ticket(tmp_path, "# doctor\n\ntest: tests/fire_color16_test.py\n")
    label = f"doctor-stale-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    try:
        rc = _launch(["run", t, label],
                     {"STANOK_REPO": str(repo),
                      "STANOK_SERVER_URL": DEAD_SERVER, "STANOK_NO_SANDBOX": "1"})
        # rc=13 is also the "ticket not found" code — pin the REASON
        # (CC-237: the refusal text lives in failures.log, not summary.json).
        failures_log = repo / "evidence" / label / "failures.log"
        errs = [line for line in failures_log.read_text(
            encoding="utf-8").splitlines() if line]
    finally:
        _cleanup(label)
    assert rc == 13, f"expected rc=13, got rc={rc}"
    assert any("already exists" in e for e in errs), errs
    assert any("edit: tests/fire_color16_test.py" in e for e in errs), errs


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


def test_runner_gate_precedence_roleleak_before_dirty_tree(tmp_path):
    # Two violations at once: parent CLAUDE.md (rc=24) AND an uncommitted file
    # (rc=22) -> the earlier gate wins: rc=24. Pins the _launch_gates order
    # (B3 moved the sequence there; a swap must be caught by a test, not by
    # the docstring).
    root = tmp_path / "prec-roleleak"
    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    (root / "CLAUDE.md").touch()
    t = _ticket(tmp_path, "# doctor\n\nplaceholder\n")
    label = f"doctor-prec-rl-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    rc = _launch(["run", t, label],
                 {"STANOK_REPO": str(repo),
                  "STANOK_SERVER_URL": DEAD_SERVER,
                  "STANOK_NO_SANDBOX": "1"})
    assert rc == 24, f"expected rc=24 (role-leak before dirty-tree), got rc={rc}"


def test_runner_gate_precedence_ticket_before_dirty_tree(tmp_path):
    # Two violations at once: missing ticket (rc=13) AND a dirty tree (rc=22)
    # -> the earlier gate wins: rc=13.
    root = tmp_path / "prec-ticket"
    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    label = f"doctor-prec-tk-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    rc = _launch(["run", root / "no-such-ticket.md", label],
                 {"STANOK_REPO": str(repo),
                  "STANOK_SERVER_URL": DEAD_SERVER,
                  "STANOK_NO_SANDBOX": "1"})
    assert rc == 13, f"expected rc=13 (ticket before dirty-tree), got rc={rc}"


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
