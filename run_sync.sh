#!/usr/bin/env bash
# run_sync.sh — один короткий вызов на ход супервизора (L1).
#
# Проблема: прогон станка длится 1100-1600s, а один Bash tool call Claude Code
# живёт максимум ~120s (default) / 600s (максимум). Долгий прямой вызов
# launch.sh убивается по таймауту, и SIGTERM может перекинуться на фоновый
# прогон (issue #45717). Решение: этот скрипт НИКОГДА не блокируется дольше
# MAX_WAIT_S и переиспользует проверенный --background режим launch.sh
# (setsid nohup внутри — переживает смерть родителя).
#
# Использование (из корня проекта):
#   ./stanok/run_sync.sh stanok/tickets/TASK-STANOK-CC-NNN.md <label> [max_wait_s]
#
# Ответ — ОДИН из двух форматов:
#   1) Полный JSON (rc/verifier/probe_result/review_verdict) — прогон завершён.
#   2) {"status":"running", ...} — прогон ещё идёт; следующий ход — ТОТ ЖЕ вызов.
#
# MAX_WAIT_S: СТРОГО меньше реального лимита Bash tool call (замерить эмпирически;
# 90 — осторожное значение, не измеренное число).

set -u
TICKET="${1:?usage: run_sync.sh <ticket.md> <label> [max_wait_s]}"
LABEL="${2:?usage: run_sync.sh <ticket.md> <label> [max_wait_s]}"
MAX_WAIT_S="${3:-90}"

REPO="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$REPO")"
EVIDENCE_FILE="$REPO/evidence/$LABEL/summary.json"
STARTED_MARK="/tmp/stanok-logs/$LABEL.started"

# Уже завершён — выводим итог и уходим.
if [[ -f "$EVIDENCE_FILE" ]]; then
    cat "$EVIDENCE_FILE"
    exit 0
fi

# Не запущен — стартуем через проверенный --background (setsid nohup внутри).
if [[ ! -f "$STARTED_MARK" ]]; then
    "$REPO/launch.sh" "$TICKET" "$LABEL" --background
    rc_launch=$?
    if [[ $rc_launch -ne 0 ]]; then
        echo "{\"status\":\"launch-failed\",\"rc\":$rc_launch,\"label\":\"$LABEL\"}" >&2
        exit $rc_launch
    fi
    mkdir -p "$(dirname "$STARTED_MARK")"
    touch "$STARTED_MARK"
fi

# Ожидание строго <= MAX_WAIT_S (шаг 5s). Не успел — честный статус, не ложный PASS.
for (( i=0; i<MAX_WAIT_S; i+=5 )); do
    if [[ -f "$EVIDENCE_FILE" ]]; then
        cat "$EVIDENCE_FILE"
        exit 0
    fi
    sleep 5
done

echo "{\"status\":\"running\",\"label\":\"$LABEL\",\"waited_s\":$MAX_WAIT_S}"
