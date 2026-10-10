"""pod_runner — the in-Pod runner (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §8).

Runs inside the worker Pod (the only code that runs there): reconstructs the
tree from the transport ConfigMap, re-inits its own git (the base commit —
the patch is `git diff base..HEAD` afterwards), DISABLES the native bwrap
sandbox in the extracted `.claude/settings.stanok.json` (O3: the K8s
boundary — NetworkPolicy + securityContext + non-root — replaces it; bwrap
cannot run under a RuntimeDefault seccomp profile), runs the in-container
session (the unchanged STANOK_IN_CONTAINER=1 path), then emits the evidence
payload (summary.json + launcher.stdout.log + changes.patch) as ONE base64
gzip-tar block between the nonce markers on stdout.

Exit contract: 0 once the payload block is emitted (the verdict is inside
the payload — a defect verdict is a SUCCESSFUL transport); 1 only if this
runner itself died before emitting (the host then treats the run as
aborted, status `missing`).
"""

import base64
import gzip
import io
import os
import subprocess
import sys
import tarfile

REPO = os.environ.get("STANOK_POD_REPO", "/stanok-work/repo")
TRANSPORT_DIR = os.environ.get("STANOK_POD_TRANSPORT", "/stanok/transport")
TICKET_PATH = os.environ.get("STANOK_POD_TICKET", "/stanok/ticket/ticket.md")
LOG_DIR = os.environ.get("STANOK_LOG_DIR", "/stanok-work/logs")
WORK = os.path.dirname(REPO)  # /stanok-work — the emptyDir mount


def _unpack(blob: str) -> None:
    raw = gzip.decompress(base64.b64decode(blob))
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        try:
            tf.extractall(REPO, filter="data")
        except TypeError:
            tf.extractall(REPO)


def main() -> int:
    label = os.environ["STANOK_LABEL"]
    nonce = os.environ["STANOK_NONCE"]

    # 1. The tree from the transport (no .git — the Pod owns its git).
    with open(os.path.join(TRANSPORT_DIR, "tree.tar.gz.b64"),
              encoding="ascii") as f:
        blob = f.read()
    os.makedirs(REPO, exist_ok=True)
    _unpack(blob)

    # The extracted tree carries the launcher package — the session runs the
    # unchanged in-container path against it.
    sys.path.insert(0, REPO)
    from launcher import k8s

    # 2. O3: the Pod-side settings rewrite (bwrap off; the filesystem deny
    # entries and the network block removed — the sandbox_config_gate would
    # otherwise rc=28 on '../evidence', absent next to the extracted tree).
    # BEFORE the base commit: the rewrite is part of the Pod's baseline, not
    # an uncommitted change — the in-Pod dirty_tree_gate (cli.py, rc=22)
    # would otherwise abort the session (live cc221, 2026-10-10).
    settings = os.path.join(REPO, ".claude", "settings.stanok.json")
    if os.path.isfile(settings):
        with open(settings, encoding="utf-8") as f:
            rewritten = k8s.disable_sandbox_settings(f.read())
        # CC-225: the Opik tracing endpoint is ENV-only — the host passes
        # the reachable backend URL via the Job env; the settings value is
        # rewritten here (claude applies settings.env natively), still
        # BEFORE the base commit. Empty env -> settings unchanged.
        rewritten = k8s.rewrite_tracing_endpoint(
            rewritten, os.environ.get("STANOK_OPIK_TRACE_URL", ""))
        with open(settings, "w", encoding="utf-8") as f:
            f.write(rewritten)

    # 3. The base commit: the patch is computed against it.
    def git(*a, check=True):
        return subprocess.run(["git", *a], cwd=REPO, check=check,
                              capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "stanok@pod.local")
    git("config", "user.name", "stanok")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD").stdout.strip()

    # 4. The session: the unchanged STANOK_IN_CONTAINER=1 path (gates, lock,
    # cmd_run). STANOK_START_COMMIT is inherited from the Job env — the
    # host HEAD at start, not the Pod's re-inited base.
    tmp = os.path.join(WORK, "tmp")
    home = os.path.join(WORK, "home")
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "STANOK_IN_CONTAINER": "1",
        "STANOK_REPO": REPO,
        "STANOK_LOG_DIR": LOG_DIR,
        "STANOK_LOCK_KEY": REPO,
        "TMPDIR": tmp,
        "CLAUDE_TMPDIR": tmp,
        "HOME": home,
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    subprocess.run(
        [sys.executable, os.path.join(REPO, "launcher", "stanok.py"),
         "run", TICKET_PATH, "--", label],
        cwd=REPO, env=env)

    # 5. changes.patch: only the writable zones (the machine's contract);
    # anything the session left elsewhere stays untracked.
    git("add", "-A", "--", "src", "tests", "docs", "scripts", check=False)
    git("commit", "-qm", "stanok-run", "--allow-empty", check=False)
    patch = subprocess.run(["git", "diff", base, "HEAD"], cwd=REPO,
                           capture_output=True).stdout

    # 6. The payload: one base64 block between the nonce markers.
    files = {"changes.patch": patch}
    run_dir = os.path.join(LOG_DIR, label)
    for name in ("summary.json", "launcher.stdout.log"):
        p = os.path.join(run_dir, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                files[name] = f.read()
    sys.stdout.write(k8s.begin_marker(nonce) + "\n" + k8s.build_payload(files)
                     + "\n" + k8s.end_marker(nonce) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
