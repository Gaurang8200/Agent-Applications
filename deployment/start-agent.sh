#!/usr/bin/env bash
# Bring the whole agent up on this machine: infrastructure, API, web, and the
# Cloudflare tunnels that expose them.
#
# Nothing here costs money. The tunnels are Cloudflare's free Quick Tunnel,
# which mints a throwaway *.trycloudflare.com hostname per run. The agent only
# runs while this machine is awake — that is the tradeoff for not paying for a
# server.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

log() { printf '\n\033[1m%s\033[0m\n' "$*"; }

pids=()
cleanup() {
  log "Stopping…"
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

# --- 1. Infrastructure -----------------------------------------------------
log "Starting Postgres, Redis, and MinIO"
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d

log "Waiting for Postgres"
for _ in $(seq 1 60); do
  if docker compose --env-file .env -f infra/docker/docker-compose.yml \
       exec -T postgres pg_isready -q 2>/dev/null; then break; fi
  sleep 1
done

log "Applying migrations"
(cd backend && ./.venv/bin/alembic upgrade head)

# --- 2. API ---------------------------------------------------------------
log "Starting the API on :8000"
./backend/run-dev.sh --port 8000 --log-level warning &
pids+=($!)

for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 1
done
curl -s http://127.0.0.1:8000/health; echo

# --- 3. Tunnel for the API ------------------------------------------------
# The tunnel must come up before the web app builds, because the browser talks
# to the API by its public hostname, and Next inlines NEXT_PUBLIC_* at build.
log "Opening a tunnel to the API"
api_log="$(mktemp -t agentapp-api-tunnel)"
cloudflared tunnel --url http://localhost:8000 --no-autoupdate >"$api_log" 2>&1 &
pids+=($!)

api_url=""
for _ in $(seq 1 40); do
  api_url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$api_log" | head -1 || true)"
  [ -n "$api_url" ] && break
  sleep 1
done
if [ -z "$api_url" ]; then
  echo "Could not obtain an API tunnel URL. Log: $api_log" >&2
  exit 1
fi
echo "API:  $api_url"

# --- 4. Web ---------------------------------------------------------------
log "Starting the web app on :3000"
(cd frontend && NEXT_PUBLIC_API_URL="$api_url" npm run dev >/dev/null 2>&1) &
pids+=($!)

for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:3000 -o /dev/null 2>/dev/null && break
  sleep 1
done

log "Opening a tunnel to the web app"
web_log="$(mktemp -t agentapp-web-tunnel)"
cloudflared tunnel --url http://localhost:3000 --no-autoupdate >"$web_log" 2>&1 &
pids+=($!)

web_url=""
for _ in $(seq 1 40); do
  web_url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$web_log" | head -1 || true)"
  [ -n "$web_url" ] && break
  sleep 1
done

cat <<EOF

$(printf '\033[1m%s\033[0m' "Agent is live")

  Open this:   ${web_url:-http://localhost:3000}
  API:         $api_url

Only ALLOWED_EMAILS in .env can sign in. Confirm that is set before sharing
the link — a Quick Tunnel URL is public to anyone who has it.

The hostnames change every run. Put the web URL behind the button on your
site, or re-copy it when you restart.

Leave this terminal open. Ctrl-C stops everything.
EOF

wait
