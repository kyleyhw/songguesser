#!/usr/bin/env bash
# Convenience launcher: load .env if present, start the server, optionally
# kick off a Cloudflare Tunnel for internet exposure.

set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PORT="${PORT:-8138}"
HOST="${HOST:-0.0.0.0}"
ADVERTISE="${ADVERTISE:-1}"
TUNNEL="${TUNNEL:-0}"

ARGS=(--host "$HOST" --port "$PORT")
[ "$ADVERTISE" = "1" ] && ARGS+=(--advertise)

if [ "$TUNNEL" = "1" ] && command -v cloudflared >/dev/null 2>&1; then
  echo "Starting Cloudflare Tunnel..."
  cloudflared tunnel --url "http://localhost:$PORT" &
  TUNNEL_PID=$!
  trap 'kill $TUNNEL_PID 2>/dev/null || true' EXIT
fi

exec uv run python -m songguesser "${ARGS[@]}"
