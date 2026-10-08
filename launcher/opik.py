"""opik — the post-run Opik trace-count sample (CC-106), out of the main path.

One best-effort HTTP sample after the verdict; never polled during a run.
"""

import json
import os
import urllib



def _opik_trace_count() -> int | None:
    """Total trace count in the 'stanok' Opik project, or None if Opik is
    unreachable. The machine exports OTLP spans to the host Opik backend
    (network=host -> localhost:8080). CC-106: sampled ONCE, fast, strictly
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


