"""Wave C F5 (TASK-NEXT-AFTER-REBOOT-2026-10-20 §7 item 6; runtime facts
corrected by measurement 2026-10-20) — transport unpack hardening.

The two unpack paths run on DIFFERENT runtimes and are hardened
differently:

  - `payload.unpack_tree` is HOST-side only: the launcher venv (measured
    3.13.13, `launch.sh` PY default) has the tarfile `filter` kwarg, so
    its old `except TypeError` fallback was a silent policy downgrade on a
    runtime where it cannot occur — removed: a TypeError must propagate.
  - `pod_runner._unpack` runs inside the Pod image, measured
    `3.11.2 (main, Oct  7 2026)` with signature
    `extractall(self, path='.', members=None, *, numeric_owner=False)` —
    NO `filter` kwarg (`docker run … python3 -c 'inspect.signature(…)'`,
    2026-10-20). The fallback is load-bearing there: without it every Pod
    run dies with TypeError. It stays: the transport is `git archive`,
    which never emits unsafe members (the same belt argument as before).

Semantics provenance: Python 3.12+ `tarfile` `filter="data"` RAISES on
unsafe members (AbsoluteLinkError / LinkOutsideDestinationError /
AbsolutePathError) rather than skipping them — documented tarfile behavior,
re-confirmed by host probe 2026-10-20 (/tmp/wc-probe.py, /tmp/wc-probe2.py).
`git archive` never emits such members, so this is hardening (belt), not a
live defect — F5 severity low, per the 2026-10-19 review.
Tests:
  1  a TypeError raised by extractall(filter=...) propagates out of
     unpack_tree and exactly one call was made — no silent unfiltered retry
     (discriminating: the pre-fix code swallows it and retries).
  2  characterization: a tar with a symlink to an absolute path raises
     AbsoluteLinkError through unpack_tree (the filter stays fail-closed).
  3  characterization (measured Pod runtime): pod_runner._unpack against
     a filter-less extractall must NOT raise — it tries filter="data",
     takes the TypeError fallback and extracts the file unfiltered.
     RED-first against the wave-C pod_runner rewrite (which raised).

Run: <stanok venv>/bin/python -m pytest launcher/tests_harness/test_k8s_unpack_hardening.py -q
"""
import base64
import gzip
import io
import tarfile

import pytest

from launcher import payload


def _tar_blob(members=b"") -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        if members:
            info = tarfile.TarInfo("src/keep.py")
            info.size = len(members)
            tf.addfile(info, io.BytesIO(members))
    return base64.b64encode(gzip.compress(buf.getvalue())).decode("ascii")


def _typeerror_filter(monkeypatch):
    """Simulate a pre-3.12 tarfile: extractall accepts no `filter` kwarg."""
    calls = []
    real = tarfile.TarFile.extractall

    def fake(self, path=None, filter=None, **kwargs):
        calls.append(filter)
        if filter is not None:
            raise TypeError(
                "extractall() got an unexpected keyword argument 'filter'")
        return real(self, path, **kwargs)

    monkeypatch.setattr(tarfile.TarFile, "extractall", fake)
    return calls


def test_unpack_tree_propagates_filter_typeerror(tmp_path, monkeypatch):
    calls = _typeerror_filter(monkeypatch)
    with pytest.raises(TypeError):
        payload.unpack_tree(_tar_blob(b"x\n"), str(tmp_path / "dest"))
    # one filtered call only — the silent no-filter retry must be gone
    assert calls == ["data"], calls
    assert not (tmp_path / "dest").exists() or not list(
        (tmp_path / "dest").glob("*"))


def test_unpack_tree_data_filter_rejects_absolute_link(tmp_path):
    # characterization (host-venv 3.13 tarfile data-filter semantics,
    # probed 2026-10-20):
    # the data filter RAISES on a symlink to an absolute target — no skip,
    # no silent unfiltered extraction.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)
    blob = base64.b64encode(gzip.compress(buf.getvalue())).decode("ascii")
    with pytest.raises(tarfile.AbsoluteLinkError):
        payload.unpack_tree(blob, str(tmp_path / "dest"))


def test_pod_runner_unpack_keeps_fallback_for_filterless_runtime(tmp_path,
                                                                 monkeypatch):
    """characterization of the measured Pod runtime (3.11.2, probe
    2026-10-20): its extractall accepts no `filter` kwarg, so
    pod_runner._unpack must try filter="data", catch the TypeError and
    extract unfiltered — the fallback is what makes the Pod work at all.
    RED-first against the wave-C rewrite, which removed the fallback and
    raised TypeError on every Pod run."""
    from launcher import pod_runner
    monkeypatch.setattr(pod_runner, "REPO", str(tmp_path / "repo"))
    calls = _typeerror_filter(monkeypatch)
    pod_runner._unpack(_tar_blob(b"x\n"))
    assert calls == ["data", None], calls
    assert (tmp_path / "repo" / "src" / "keep.py").read_bytes() == b"x\n"
