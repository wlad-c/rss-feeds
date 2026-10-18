#!/usr/bin/env bash
# Continuous free STT waves (faster-whisper). Sole sqlite writer while running.
set -euo pipefail
cd "$(dirname "$0")/.."
WAVE=0
while true; do
  WAVE=$((WAVE + 1))
  LOG="/tmp/stt-loop-w${WAVE}.log"
  echo "==== STT wave $WAVE $(date -u) ====" | tee -a /tmp/stt-loop.log
  python3 scripts/selective_stt.py \
    --engine faster-whisper \
    --model small \
    --max-episodes 80 \
    --max-minutes 800 \
    --years 2023,2024,2025,2026 \
    2>&1 | tee -a "$LOG" | tee -a /tmp/stt-loop.log
  OK=$(grep -c 'ok via=faster-whisper' "$LOG" || true)
  echo "wave $WAVE ok=$OK $(date -u)" | tee -a /tmp/stt-loop.log
  if [[ "${OK:-0}" -eq 0 ]]; then
    echo "no STT progress; sleeping 600s before retry" | tee -a /tmp/stt-loop.log
    sleep 600
  else
    sleep 5
  fi
done
