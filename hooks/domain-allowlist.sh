#!/usr/bin/env bash
# domain-allowlist.sh — PreToolUse hook (WebFetch). deny-by-default: статический
# allowlist 9 доменов (как ALLOWED_WEBFETCH_HOSTS в stanok-sdk.py, без raw.*).
# URL-хост вне списка -> deny (fail-closed). Без Telegram/approval.
# WebFetch остаётся ВНЕ settings allow И ВНЕ deny (правило trusted-mode short-circuit)
# — реальный гейт домена — этот hook; can_use_tool — ремень.
# REPO_ROOT выводится из расположения скрипта — хук переносимый.
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

# ПАТЧ 3 (SSRF/DNS-rebinding): резолв hostname -> IP ДО allowlist-решения.
# deny, если ЛЮБОЙ из резолвнутых IP — private (RFC1918/ULA), loopback или
# link-local — независимо от membership в allowlist (защита от DNS-rebinding
# и подмены /etc/hosts на разрешённом домене). Fail-closed: любой bad IP -> deny.
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
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"domain-allowlist: SSRF-guard — %s резолвится в приватный/loopback/link-local адрес %s"}}' "$HOST" "$BAD_IPS"
    exit 0
fi

if printf '%s' "$HOST" | grep -qE "$ALLOWED"; then   # allow
  printf '{"systemMessage":"domain-allowlist: allow %s"}' "$HOST"
  exit 0
fi

mkdir -p "$LOG_DIR"
echo "$(date +%T) DENY host=$HOST url=$URL" >> "$LOG"
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"domain-allowlist: %s вне разрешённых доменов"}}' "$HOST"
exit 0
