#!/usr/bin/env bash
# Free publisher/caption upgrades. Run ONLY when no other sqlite writer is live.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==== publisher burst $(date -u) ===="
# Refuse if selective_stt (or other harvesters) hold the DB.
if pgrep -af 'selective_stt|harvest_youtube|fetch_gap_publisher|fetch_omny|fetch_more_publisher' | grep -v "$$" | grep -v run_publisher >/dev/null; then
  echo "ABORT: another transcript writer is running" >&2
  pgrep -af 'selective_stt|harvest_youtube|fetch_gap|fetch_omny|fetch_more' || true
  exit 2
fi
python3 scripts/fetch_omny_transcripts.py
python3 scripts/fetch_gap_publisher_transcripts.py
python3 scripts/fetch_more_publisher_transcripts.py
echo "==== publisher burst done $(date -u) ===="
