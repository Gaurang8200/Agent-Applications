#!/usr/bin/env bash
# One-time setup of a named Cloudflare tunnel, so the agent has a stable
# hostname instead of a throwaway one that changes every run.
#
#   ./deployment/setup-tunnel.sh agent.example.com
#
# Prerequisite: the domain's DNS must already be on Cloudflare. A named tunnel
# is routed by a CNAME to <uuid>.cfargotunnel.com, and that only resolves
# through Cloudflare — it cannot be added at another DNS provider.
#
# Run this once. Afterwards ./deployment/start-agent.sh uses the named tunnel.
set -euo pipefail

hostname="${1:-}"
if [ -z "$hostname" ]; then
  echo "Usage: $0 <hostname>   e.g. $0 agent.example.com" >&2
  exit 1
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
tunnel_name="agent-applications"

log() { printf '\n\033[1m%s\033[0m\n' "$*"; }

command -v cloudflared >/dev/null 2>&1 || {
  echo "cloudflared not found. Install it: brew install cloudflared" >&2
  exit 1
}

# --- 1. Authenticate ------------------------------------------------------
# Writes a certificate for the chosen zone into ~/.cloudflared. This opens a
# browser; pick the zone that serves the site.
if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
  log "Authorising cloudflared (a browser window will open)"
  cloudflared tunnel login
fi

# --- 2. Create the tunnel -------------------------------------------------
if cloudflared tunnel list --output json 2>/dev/null | grep -q "\"name\":\"$tunnel_name\""; then
  log "Tunnel '$tunnel_name' already exists"
else
  log "Creating tunnel '$tunnel_name'"
  cloudflared tunnel create "$tunnel_name"
fi

tunnel_id="$(cloudflared tunnel list --output json | python3 -c "
import json, sys
for t in json.load(sys.stdin):
    if t['name'] == '$tunnel_name':
        print(t['id']); break
")"
if [ -z "$tunnel_id" ]; then
  echo "Could not determine the tunnel id." >&2
  exit 1
fi
echo "Tunnel id: $tunnel_id"

# --- 3. Route DNS ---------------------------------------------------------
# Creates (or updates) the proxied CNAME for the hostname in Cloudflare.
log "Pointing $hostname at the tunnel"
cloudflared tunnel route dns "$tunnel_name" "$hostname" || \
  echo "Route already exists, continuing."

# --- 4. Write the config --------------------------------------------------
# Both the web app and the API are served from one hostname: everything under
# /api goes to the API, the rest to the web app. One hostname keeps the browser
# on a single origin, so no CORS configuration is needed.
config_dir="$HOME/.cloudflared"
config_file="$config_dir/config.yml"
mkdir -p "$config_dir"

cat > "$config_file" <<EOF
tunnel: $tunnel_id
credentials-file: $config_dir/$tunnel_id.json

ingress:
  - hostname: $hostname
    path: ^/(api|health|docs|openapi.json)
    service: http://localhost:8000
  - hostname: $hostname
    service: http://localhost:3000
  - service: http_status:404
EOF
echo "Wrote $config_file"

# --- 5. Record the hostname for the launcher ------------------------------
env_file="$root/.env"
if grep -q '^PUBLIC_HOSTNAME=' "$env_file" 2>/dev/null; then
  sed -i '' "s|^PUBLIC_HOSTNAME=.*|PUBLIC_HOSTNAME=$hostname|" "$env_file"
else
  printf '\nPUBLIC_HOSTNAME=%s\n' "$hostname" >> "$env_file"
fi

cat <<EOF

$(printf '\033[1m%s\033[0m' "Named tunnel ready")

  Public URL:  https://$hostname

Next:
  1. Start everything:  ./deployment/start-agent.sh
  2. On the portfolio project set VITE_AGENT_APP_URL=https://$hostname
     (Vercel > Settings > Environment Variables), then redeploy.

The hostname is now stable, so that value never needs changing again.
Access stays restricted to ALLOWED_EMAILS in .env.
EOF
