"""P1 (O3, operator 2026-10-10: отказ от bwrap) — the Pod-side settings rewrite.

The machine's native sandbox (claude-code bwrap) is DISABLED in the Pod: the
K8s boundary (NetworkPolicy + securityContext + non-root) replaces it, and
bwrap cannot run under a RuntimeDefault seccomp profile. The Pod runner
rewrites `.claude/settings.stanok.json` in the extracted tree BEFORE the
session: sandbox.enabled=false, failIfUnavailable=false, the filesystem deny
entries and the network block REMOVED (the sandbox_config_gate would
otherwise rc=28 on `../evidence` — a path that does not exist next to the
extracted tree). Everything else (env, permissions) is preserved byte-for-
byte. Tests:
  1  sandbox disabled, filesystem/network blocks removed
  2  env and permissions survive unchanged

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_pod_settings.py -q
"""
import json

from launcher import k8s

SETTINGS = json.dumps({
    "env": {"ANTHROPIC_AUTH_TOKEN": "local-dummy"},
    "permissions": {"allow": ["Read", "Bash"], "deny": ["Read(.git/**)"]},
    "sandbox": {
        "enabled": True,
        "failIfUnavailable": True,
        "enableWeakerNestedSandbox": True,
        "filesystem": {"denyWrite": ["../evidence"], "denyRead": ["../launcher"]},
        "network": {"allowedDomains": ["192.168.8.131"]},
    },
})


def test_sandbox_disabled_and_blocks_removed():
    out = json.loads(k8s.disable_sandbox_settings(SETTINGS))
    assert out["sandbox"]["enabled"] is False
    assert out["sandbox"]["failIfUnavailable"] is False
    assert "filesystem" not in out["sandbox"]
    assert "network" not in out["sandbox"]


def test_env_and_permissions_untouched():
    out = json.loads(k8s.disable_sandbox_settings(SETTINGS))
    assert out["env"] == {"ANTHROPIC_AUTH_TOKEN": "local-dummy"}
    assert out["permissions"] == {"allow": ["Read", "Bash"],
                                  "deny": ["Read(.git/**)"]}
