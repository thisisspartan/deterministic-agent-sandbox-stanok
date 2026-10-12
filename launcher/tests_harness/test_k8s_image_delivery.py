"""Image delivery by DIGEST (operator 2026-10-12, close of the cc248 incident).

The incident: kubelet image GC evicted the tag-pinned image (disk 85%) and the
manual `docker save | sudo k3s ctr import` transport was invisible to the
launch -> ImagePullBackOff. The fix: setup.sh pushes to the node-local
registry; k8s._image_ref resolves the pushed RepoDigest at launch and the Job
templates render the DIGEST reference — kubelet re-pulls the exact image after
any GC. Fail-closed: an image not pushed aborts rc=16 BEFORE any cluster
resource, with the fix named (setup.sh / k8s/setup-registry.sh). Tests:
  1 _image_ref: resolves the registry-prefixed digest, ignores foreign entries
  2 _image_ref: image absent locally -> reason names setup.sh (build)
  3 _image_ref: RepoDigests null (exists, never pushed) -> reason names the
    registry + setup.sh — no crash on the `null` JSON
  4 _image_ref: unparseable inspect output -> same not-pushed reason
  5 host_launch_k8s: unpushed image -> rc=16 before ANY cluster call, no
    marker; failures.log names the fix
  6 host_launch_k8s: the rendered worker Job carries the digest reference

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_image_delivery.py -q
"""
import argparse
import json
import os

from launcher import k8s
from launcher.config import Config

DIGEST = "192.168.122.156:5000/stanok-machine@sha256:deadbeef"


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


# --- 1-4: _image_ref branches (docker inspect mocked, no real docker) -------------

def _fake_docker(monkeypatch, *, rc=0, stdout="", stderr=""):
    seen = []

    def fake_run(argv, **kw):
        assert argv[0] == "docker" and argv[1] == "inspect"
        seen.append(argv)
        return _FakeCompleted(rc, stdout, stderr)
    monkeypatch.setattr(k8s.subprocess, "run", fake_run)
    return seen


def test_image_ref_resolves_registry_digest(monkeypatch):
    _fake_docker(monkeypatch, stdout=json.dumps([
        "docker.io/library/stanok-machine@sha256:aaa",  # foreign — never used
        DIGEST,
    ]))
    ref, err = k8s._image_ref(Config())
    assert err is None
    assert ref == DIGEST  # the registry-prefixed entry, not the foreign one


def test_image_ref_absent_image_names_build(monkeypatch):
    _fake_docker(monkeypatch, rc=1, stderr="No such image")
    ref, err = k8s._image_ref(Config())
    assert ref is None
    assert "not found locally" in err and "setup.sh" in err


def test_image_ref_null_digests_is_not_pushed(monkeypatch):
    # docker inspect prints `null` for an image that exists but was never
    # pushed — must become the named fix, never a TypeError.
    _fake_docker(monkeypatch, stdout="null")
    ref, err = k8s._image_ref(Config())
    assert ref is None
    assert "not pushed" in err and Config().registry in err and "setup.sh" in err


def test_image_ref_unparseable_output_is_not_pushed(monkeypatch):
    _fake_docker(monkeypatch, stdout="not json")
    ref, err = k8s._image_ref(Config())
    assert ref is None
    assert "not pushed" in err


# --- 5-6: host_launch_k8s wiring (cluster + docker all mocked) -------------------

def _k8s_repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(tmp_path / "logs"))


def _k8s_args(tmp_path):
    ticket = tmp_path / "ticket.md"
    ticket.write_text("test: tests/x_test.py\nrun.sh: exists\n", encoding="utf-8")
    return argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket), local_retries=0, extra=[])


def _mock_launch_env(monkeypatch):
    monkeypatch.setattr(k8s.shutil, "which", lambda name: "/usr/bin/kubectl")
    # the unified preflight is mocked out here — these tests target the
    # delivery point (_image_ref); the preflight checks: test_k8s_preflight.py
    monkeypatch.setattr(k8s, "_preflight", lambda cfg: None)
    monkeypatch.setattr(k8s, "pack_tree", lambda root: "x")
    monkeypatch.setattr(k8s, "transport_ok", lambda blob: True)


def test_unpushed_image_aborts_rc16_before_any_cluster_call(tmp_path, monkeypatch):
    repo, cfg = _k8s_repo(tmp_path)
    args = _k8s_args(tmp_path)
    _mock_launch_env(monkeypatch)
    monkeypatch.setattr(k8s, "_image_ref",
                        lambda cfg: (None, "image not pushed to the registry — run setup.sh"))
    calls = []
    monkeypatch.setattr(k8s, "_kubectl",
                        lambda *a, **k: calls.append(a) or _FakeCompleted(0))
    marker = str(tmp_path / ".running")
    rc = k8s.host_launch_k8s(cfg, args, marker)
    assert rc == 16  # infrastructure defect, not a ticket defect
    assert calls == []  # no ConfigMap/Job was created
    assert not os.path.exists(marker)  # no run was started
    # the refusal names the fix (failures.log, CC-237)
    failures = os.path.join(cfg.summary_dir("lbl"), "failures.log")
    assert "setup.sh" in open(failures, encoding="utf-8").read()


def test_rendered_worker_job_carries_the_digest(tmp_path, monkeypatch):
    repo, cfg = _k8s_repo(tmp_path)
    args = _k8s_args(tmp_path)
    _mock_launch_env(monkeypatch)
    monkeypatch.setattr(k8s, "_image_ref", lambda cfg: (DIGEST, None))
    manifests = []

    def fake(*a, **k):
        if a[:2] == ("create", "-f"):
            manifests.append(k.get("input_text") or "")
        return _FakeCompleted(0)
    monkeypatch.setattr(k8s, "_kubectl", fake)
    monkeypatch.setattr(k8s, "_pod_of_job", lambda *a, **k: None)
    monkeypatch.setattr(k8s, "_wait_job_terminal", lambda *a, **k: "failed")
    k8s.host_launch_k8s(cfg, args, str(tmp_path / ".running"))
    assert manifests  # the worker Job was rendered and sent
    assert f"image: {DIGEST}" in manifests[0]
    assert "stanok-machine:latest" not in manifests[0]  # never the tag form
