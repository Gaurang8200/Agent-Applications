#!/usr/bin/env bash
# Run the agent on this machine, indefinitely.
#
# Brings up infrastructure, applies migrations, and starts the API and web app.
# With AUTOPILOT_ENABLED=true the API discovers, scores, and prepares
# applications on its own interval — nothing else needs to be running, and no
# tunnel is involved because everything stays on localhost.
#
#   ./deployment/run-local.sh
#
# Open http://localhost:3000. Ctrl-C stops everything.
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

# --- Preflight ------------------------------------------------------------
docker info >/dev/null 2>&1 || {
  echo "Docker is not running. Start Docker Desktop, then run this again." >&2
  exit 1
}
[ -f .env ] || { echo "No .env file. Copy .env.example and fill it in." >&2; exit 1; }

# --- Infrastructure -------------------------------------------------------
log "Starting Postgres, Redis, and MinIO"
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d

log "Waiting for Postgres"
for _ in $(seq 1 60); do
  docker compose --env-file .env -f infra/docker/docker-compose.yml \
    exec -T postgres pg_isready -q 2>/dev/null && break
  sleep 1
done

log "Applying migrations"
(cd backend && ./.venv/bin/alembic upgrade head)

# --- API ------------------------------------------------------------------
# run-dev.sh sets the library path LibreOffice needs for PDF rendering.
log "Starting the API on :8000"
./backend/run-dev.sh --port 8000 --log-level info &
pids+=($!)

for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 1
done
health="$(curl -s http://127.0.0.1:8000/health || true)"
echo "$health"
case "$health" in
  *'"llm_enabled":false'*)
    echo "Warning: ANTHROPIC_API_KEY is not set, so scoring and tailoring will be skipped." >&2 ;;
esac

# --- Web ------------------------------------------------------------------
log "Starting the web app on :3000"
(cd frontend && npm run dev >/dev/null 2>&1) &
pids+=($!)

for _ in $(seq 1 90); do
  curl -sf http://127.0.0.1:3000 -o /dev/null 2>/dev/null && break
  sleep 1
done

autopilot="$(grep -E '^AUTOPILOT_ENABLED=' .env | cut -d= -f2 || echo false)"
interval="$(grep -E '^AUTOPILOT_INTERVAL_MINUTES=' .env | cut -d= -f2 || echo 180)"

cat <<EOF

$(printf '\033[1m%s\033[0m' "Agent is running")

  Open:       http://localhost:3000
  Autopilot:  ${autopilot} (every ${interval} minutes)
  Documents:  ${HOME}/AgentApplications/<Company>/

Each cycle discovers new German postings, scores them, and prepares tailored
documents for the best matches. Everything stops at "ready for review" — open
the board and submit the ones you want yourself.

Keep this terminal open and the machine awake. To stop sleep from pausing the
agent, run this in another terminal:

  caffeinate -dimsu -w \$\$

Ctrl-C stops everything.
EOF

wait
