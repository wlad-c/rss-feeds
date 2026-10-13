#!/usr/bin/env bash
# Start the Poll Position feed locally and expose it via an ephemeral Cloudflare Tunnel.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DATA_DIR="${DATA_DIR:-$ROOT/data}"
export PORT="${PORT:-8787}"
export SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL_SECONDS:-3600}"
export PYTHONPATH="$ROOT/poll-position"
export PATH="${HOME}/.local/bin:${HOME}/.deno/bin:${PATH}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is required: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" >&2
  exit 1
fi

python3 "$ROOT/poll-position/server.py" &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for local port
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/rss.xml" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "Local feed is up on http://127.0.0.1:${PORT}/"
echo "Starting Cloudflare quick tunnel (Ctrl+C to stop)…"
cloudflared tunnel --url "http://127.0.0.1:${PORT}"
