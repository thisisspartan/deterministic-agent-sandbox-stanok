"""opik — the post-run Opik trace-count sample (CC-106), out of the main path.

One best-effort HTTP sample after the verdict; never polled during a run.
"""

import json
import os
import urllib.request



def _opik_trace_count() -> int | None:
    """Total trace count in the 'stanok' Opik project, or None if Opik is
    unreachable. The machine exports OTLP spans to the host Opik backend
    (reachable only outside the stanok-net bridge — see opik_traces_field).
    CC-106: sampled ONCE, fast, strictly
    after the verdict is formed (no pre-run baseline, no settle loop) — an
    unreachable backend (None) never delays or alters the run.

    Port map (PLAN-AUDIT B5 decision, 2026-10-08): the self-hosted Opik
    backend is pinned at :8080 on the supervisor host — both tracing points
    default to it in ONE decision: STANOK_OPIK_URL below and
    BETA_TRACING_ENDPOINT in .claude/settings.stanok.json (the machine's
    OTLP export target). llama-server is moved off :8080 by
    STANOK_SERVER_URL/--host; the defaults collide only if llama-server is
    run locally on :8080 — the port map is a deploy decision, not code."""
    if os.environ.get("STANOK_SKIP_OPIK_CHECK") == "1":
        return None
    base = os.environ.get("STANOK_OPIK_URL", "http://localhost:8080")
    url = f"{base}/v1/private/traces?project_name=stanok&limit=1"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(url), timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        total = data.get("total")
        return total if isinstance(total, int) else None
    except Exception:
        return None


def _trace_matches(trace: dict, session_id: str) -> bool:
    """One trace belongs to this session iff metadata.thread_id matches
    (the same client-side filter as opik-traces.py, CC-159)."""
    return (trace.get("metadata") or {}).get("thread_id") == session_id


def session_trace_count(session_id: str, since_iso: str) -> int | None:
    """CC-225: the host's proof that the Pod's OTLP export actually reached
    Opik — the count of traces in the 'stanok' project whose thread_id is
    this session. The API ignores query filters (CC-159): paginate and
    filter client-side. The list is newest-first (measured 2026-10-10), so
    the scan early-stops when a whole page is older than the run start —
    bounded to the run window, not the project history. None when Opik is
    unreachable (never a 0 masquerade); 0 is a real measurement: the spans
    never arrived."""
    if os.environ.get("STANOK_SKIP_OPIK_CHECK") == "1":
        return None
    base = os.environ.get("STANOK_OPIK_URL", "http://localhost:8080")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    count = 0
    page = 1
    while page <= 200:
        url = f"{base}/v1/private/traces?project_name=stanok&size=100&page={page}"
        try:
            with opener.open(urllib.request.Request(url), timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            return None
        items = data.get("content", [])
        if not items:
            break
        for t in items:
            if _trace_matches(t, session_id):
                count += 1
        oldest = min((t.get("start_time") or "") for t in items)
        if oldest and oldest < since_iso:
            break  # newest-first: everything below is older than the run
        if page * 100 >= data.get("total", 0):
            break
        page += 1
    return count


def opik_traces_field():
    """The value of summary.json's `opik_traces` field (S4, SPEC-NETWORK R5).

    In the worker container the field is the literal "disabled": the
    stanok-net bridge closes the path to the host Opik backend BY DESIGN
    (the machine's OTLP export target is the host's :8080), and the field
    must be present and explicit — not 0/null masquerading as "zero traces".
    Outside the container (host no-sandbox runs) the existing best-effort
    count applies unchanged."""
    if os.environ.get("STANOK_IN_CONTAINER") == "1":
        return "disabled"
    return _opik_trace_count()


