#!/usr/bin/env bash
# domain-allowlist.sh — PreToolUse hook (WebFetch). deny-by-default: a static
# allowlist of 9 domains (as ALLOWED_WEBFETCH_HOSTS in stanok-sdk.py, without raw.*).
# URL host not in the list -> deny (fail-closed). No Telegram/approval.
# WebFetch stays OUTSIDE the settings allow AND outside deny (trusted-mode short-circuit rule)
# — the real domain gate is this hook; can_use_tool is the belt.
# REPO_ROOT is derived from the script location — the hook is portable.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$REPO_ROOT/.stanok-logs"
LOG="$LOG_DIR/domain-allowlist.log"

ALLOWED="^(arxiv\.org|github\.com|docs\.anthropic\.com|code\.claude\.com|developer\.mozilla\.org|nodejs\.org|docs\.python\.org|npmjs\.com|pypi\.org)$"

INPUT="$(cat)"
URL="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    print(json.load(sys.stdin).get('tool_input',{}).get('url',''))
except Exception:
    print('')
")"
[ -n "$URL" ] || exit 0

HOST="$(printf '%s' "$URL" | python3 -c "
import sys
from urllib.parse import urlparse
try:
    h = urlparse(sys.stdin.read().strip()).hostname or ''
    print(h[4:] if h.startswith('www.') else h)
except Exception:
    print('')
")"
[ -n "$HOST" ] || exit 0

# PATCH 3 (SSRF/DNS-rebinding): resolve hostname -> IP BEFORE the allowlist decision.
# deny if ANY of the resolved IPs is private (RFC1918/ULA), loopback, or
# link-local — regardless of membership in the allowlist (protection against DNS-rebinding
# and /etc/hosts substitution on an allowed domain). Fail-closed: any bad IP -> deny.
IP_CHECK="$(printf '%s' "$HOST" | python3 -c "
import ipaddress, socket, sys
host = sys.stdin.read().strip()
bad, all_ips = [], []
for family in (socket.AF_INET, socket.AF_INET6):
    try:
        for res in socket.getaddrinfo(host, None, family, socket.SOCK_STREAM):
            ip = res[4][0]
            all_ips.append(ip)
            try:
                a = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if a.is_private or a.is_loopback or a.is_link_local:
                bad.append(ip)
    except OSError:
        pass
print(('BAD ' + ','.join(bad)) if bad else 'OK')
")"
if [ "${IP_CHECK%% *}" = "BAD" ]; then
    BAD_IPS="${IP_CHECK#BAD }"
    mkdir -p "$LOG_DIR"
    echo "$(date +%T) DENY SSRF host=$HOST ip=$BAD_IPS url=$URL" >> "$LOG"
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"domain-allowlist: SSRF-guard — %s resolves to a private/loopback/link-local address %s"}}' "$HOST" "$BAD_IPS"
    exit 0
fi

if printf '%s' "$HOST" | grep -qE "$ALLOWED"; then   # allow
  printf '{"systemMessage":"domain-allowlist: allow %s"}' "$HOST"
  exit 0
fi

mkdir -p "$LOG_DIR"
echo "$(date +%T) DENY host=$HOST url=$URL" >> "$LOG"
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"domain-allowlist: %s is outside the allowed domains"}}' "$HOST"
exit 0
