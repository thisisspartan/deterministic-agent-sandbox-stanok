"""Preflight must work when ONLY gates is imported (regression, 2026-10-08).

gates.py/opik.py use `urllib.request.*` behind a plain `import urllib` —
the submodule is not imported, so the call raises AttributeError unless some
other module happens to import urllib.request as a side effect. The C refactor
(hub gutted) removed that accidental cover: the launch-path preflight died
with rc=20 "Server unavailable (AttributeError)" while the server was live.
The subprocess below imports ONLY launcher.gates+launcher.config against a
local /props stub:
before the fix it exits 1 (AttributeError -> None), after the fix 0.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_server_preflight_import.py -q
"""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class _PropsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server API name
        body = json.dumps({"default_generation_settings": {"n_ctx": 4096}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


def test_fetch_server_props_with_only_gates_imported():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PropsHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from launcher import gates\n"
            "from launcher.config import Config\n"
            "props = gates._fetch_server_props(Config(server_url=%r))\n"
            "sys.exit(0 if props else 1)\n"
        ) % (str(REPO_ROOT), f"http://127.0.0.1:{port}")
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
        )
        assert proc.returncode == 0, (
            "gates._fetch_server_props failed with only gates imported "
            f"(likely AttributeError on urllib.request): {proc.stderr}"
        )
    finally:
        server.shutdown()
