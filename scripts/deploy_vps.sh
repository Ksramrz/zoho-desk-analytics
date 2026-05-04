#!/usr/bin/env bash
# One-shot deployer for roomvu Zoho analytics on Hostinger VPS.
# Idempotent. Safe to re-run.
# Required env vars supplied at invocation time:
#   ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_ORG_ID

set -euo pipefail

LOG=/var/log/roomvu-deploy.log
exec > >(tee -a "$LOG") 2>&1
echo "=== roomvu deploy starting $(date -u +%FT%TZ) ==="

if [[ $EUID -ne 0 ]]; then
  echo "Must run as root"; exit 1
fi

REPO_URL="https://github.com/Ksramrz/zoho-desk-analytics.git"
APP_DIR="/opt/zoho-desk-analytics"
SUBDOMAIN="roomvu.cashvers.com"

# Internal-only ports (do not collide with existing nginx/php on 80/443).
BACKEND_PORT="${BACKEND_PORT:-18000}"
FRONTEND_PORT="${FRONTEND_PORT:-18080}"
METABASE_PORT="${METABASE_PORT:-13000}"
DB_PORT="${DB_PORT:-15432}"

# Accept Zoho creds via env or positional args 1..4.
ZOHO_CLIENT_ID="${ZOHO_CLIENT_ID:-${1:-}}"
ZOHO_CLIENT_SECRET="${ZOHO_CLIENT_SECRET:-${2:-}}"
ZOHO_REFRESH_TOKEN="${ZOHO_REFRESH_TOKEN:-${3:-}}"
ZOHO_ORG_ID="${ZOHO_ORG_ID:-${4:-}}"

if [[ -z "$ZOHO_CLIENT_ID" || -z "$ZOHO_CLIENT_SECRET" || -z "$ZOHO_REFRESH_TOKEN" || -z "$ZOHO_ORG_ID" ]]; then
  echo "Missing Zoho creds (env or args). Aborting."; exit 1
fi

echo "--- Step 1: install Docker + Compose ---"
if ! command -v docker >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi
docker --version
docker compose version

echo "--- Step 2: fetch repo into $APP_DIR ---"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch --all --prune
  git -C "$APP_DIR" reset --hard origin/main
fi

echo "--- Step 3: write .env (secrets local-only) ---"
cat > "$APP_DIR/.env" <<EOF
ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID}
ZOHO_CLIENT_SECRET=${ZOHO_CLIENT_SECRET}
ZOHO_REFRESH_TOKEN=${ZOHO_REFRESH_TOKEN}
ZOHO_ORG_ID=${ZOHO_ORG_ID}
ZOHO_ACCOUNTS_URL=https://accounts.zohocloud.ca
ZOHO_BASE_URL=https://desk.zohocloud.ca/api/v1
SYNC_LOOKBACK_DAYS=31
SYNC_OVERLAP_HOURS=24
DATABASE_URL=postgresql://postgres:postgres@db:5432/zoho_analytics
EOF
chmod 600 "$APP_DIR/.env"

echo "--- Step 4: rewrite host ports to loopback-only (avoid 80/443 conflicts) ---"
# Remove any prior override and rewrite the published ports in the base compose.
rm -f "$APP_DIR/docker-compose.override.yml"
sed -i -E 's|^( +)- "8000:8000"|\1- "127.0.0.1:'"${BACKEND_PORT}"':8000"|' "$APP_DIR/docker-compose.yml"
sed -i -E 's|^( +)- "80:80"|\1- "127.0.0.1:'"${FRONTEND_PORT}"':80"|' "$APP_DIR/docker-compose.yml"
sed -i -E 's|^( +)- "3000:3000"|\1- "127.0.0.1:'"${METABASE_PORT}"':3000"|' "$APP_DIR/docker-compose.yml"

echo "--- Step 5: bring stack up ---"
cd "$APP_DIR"
docker compose pull || true
docker compose up -d --build
sleep 8
docker compose ps

echo "--- Step 6: configure nginx vhost for $SUBDOMAIN -> Metabase ---"
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/conf.d /etc/ssl/roomvu

# Generate a self-signed cert for the new vhost (CF connects to origin via
# HTTPS on Full/Strict modes; this cert lets nginx accept those connections
# without touching the existing Laravel/cashvers SSL setup).
ROOMVU_CRT=/etc/ssl/roomvu/roomvu.crt
ROOMVU_KEY=/etc/ssl/roomvu/roomvu.key
if ! command -v openssl >/dev/null 2>&1; then
  apt-get install -y openssl
fi
if [[ ! -s "$ROOMVU_CRT" || ! -s "$ROOMVU_KEY" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$ROOMVU_KEY" -out "$ROOMVU_CRT" \
    -subj "/CN=${SUBDOMAIN}" -addext "subjectAltName=DNS:${SUBDOMAIN}" \
    >/dev/null 2>&1 || \
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$ROOMVU_KEY" -out "$ROOMVU_CRT" \
    -subj "/CN=${SUBDOMAIN}" >/dev/null 2>&1
  chmod 600 "$ROOMVU_KEY"
fi

VHOST_BODY=$(cat <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${SUBDOMAIN};

    client_max_body_size 50m;

    # Lightweight marker so we can verify which vhost is actually answering.
    location = /__roomvu_health {
        default_type text/plain;
        return 200 "roomvu-vhost-OK\n";
    }

    # Backend (FastAPI / Zoho sync) lives under /zsync/ so it does not
    # collide with Metabase's own /api/* endpoints. Trailing slash on
    # proxy_pass rewrites /zsync/foo -> /foo on the upstream.
    location /zsync/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT}/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
    }

    location / {
        proxy_pass http://127.0.0.1:${METABASE_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 600s;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ${SUBDOMAIN};

    ssl_certificate ${ROOMVU_CRT};
    ssl_certificate_key ${ROOMVU_KEY};
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 50m;

    location = /__roomvu_health {
        default_type text/plain;
        return 200 "roomvu-vhost-OK-tls\n";
    }

    location /zsync/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT}/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
    }

    location / {
        proxy_pass http://127.0.0.1:${METABASE_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 600s;
    }
}
EOF
)

# Detect whether nginx.conf already includes sites-enabled or only conf.d.
# Write the vhost to ONE location only to avoid "conflicting server name"
# duplicate-server warnings.
NG_CONF=/etc/nginx/sites-available/roomvu-cashvers.conf
NG_LINK=/etc/nginx/sites-enabled/roomvu-cashvers.conf
NG_CONFD=/etc/nginx/conf.d/roomvu-cashvers.conf

rm -f "$NG_CONFD" "$NG_LINK" "$NG_CONF"
if grep -q "sites-enabled" /etc/nginx/nginx.conf 2>/dev/null; then
  echo "$VHOST_BODY" > "$NG_CONF"
  ln -sf "$NG_CONF" "$NG_LINK"
else
  echo "$VHOST_BODY" > "$NG_CONFD"
fi

# Make sure nginx includes sites-enabled (some Hostinger images use conf.d only).
if ! grep -q "sites-enabled" /etc/nginx/nginx.conf 2>/dev/null; then
  if grep -q "include /etc/nginx/conf.d" /etc/nginx/nginx.conf; then
    sed -i '/include \/etc\/nginx\/conf.d/a \    include /etc/nginx/sites-enabled/*;' /etc/nginx/nginx.conf
  fi
fi

if command -v nginx >/dev/null 2>&1; then
  nginx -t
  systemctl reload nginx || systemctl restart nginx || true
else
  echo "nginx not installed; installing minimal nginx ..."
  apt-get install -y nginx
  nginx -t && systemctl enable --now nginx
fi

echo "--- nginx vhost status (grep loaded conf for our server_name) ---"
nginx -T 2>/dev/null | grep -n -E "server_name .*${SUBDOMAIN}|__roomvu_health|listen .*443" | head -20 || echo "WARN: roomvu vhost markers NOT found in active nginx config"

echo "--- internal upstream sanity ---"
echo "Backend  127.0.0.1:${BACKEND_PORT}/api/health -> $(curl -fsS --max-time 5 http://127.0.0.1:${BACKEND_PORT}/api/health || echo FAIL)"
echo "Metabase 127.0.0.1:${METABASE_PORT}/api/health -> $(curl -fsS --max-time 5 http://127.0.0.1:${METABASE_PORT}/api/health || echo FAIL)"
echo "Vhost via Host header (HTTP)  -> $(curl -fsS --max-time 5 -H 'Host: ${SUBDOMAIN}' http://127.0.0.1/__roomvu_health || echo FAIL)"
echo "Vhost via Host header (HTTPS) -> $(curl -fsSk --max-time 5 -H 'Host: ${SUBDOMAIN}' https://127.0.0.1/__roomvu_health || echo FAIL)"

echo "--- Step 7: optional initial Zoho sync (off by default; set RUN_DEPLOY_SYNC=1 to enable) ---"
if [ "${RUN_DEPLOY_SYNC:-0}" = "1" ]; then
  sleep 4
  curl -fsS -X POST "http://127.0.0.1:${BACKEND_PORT}/api/sync/trigger?force_full_lookback=true&lookback_days=31" \
    -H 'Content-Type: application/json' -d '{}' || true
else
  echo "Skipping deploy-time sync (RUN_DEPLOY_SYNC is not 1). Avoids hammering Zoho on every redeploy."
fi
echo

echo "--- Step 8: status report ---"
docker compose ps
echo "Listening sockets:"
ss -tlnp | grep -E ":(${BACKEND_PORT}|${FRONTEND_PORT}|${METABASE_PORT}|${DB_PORT}|80|443)\b" || true

echo "=== roomvu deploy finished $(date -u +%FT%TZ) ==="
echo "Metabase URL (after DNS): http://${SUBDOMAIN}/"
echo "Backend API health: curl http://127.0.0.1:${BACKEND_PORT}/api/health"
