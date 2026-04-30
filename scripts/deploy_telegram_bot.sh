#!/usr/bin/env bash
# Pulls the latest Telegram bot files and (re)starts the backend with the bot enabled.
# Usage: bash deploy_telegram_bot.sh <TELEGRAM_BOT_TOKEN>
# Idempotent. Safe to run multiple times.
set -euo pipefail

TOKEN="${1:-}"
APP_DIR="${APP_DIR:-/opt/zoho-desk-analytics}"
BACKEND_PORT="${BACKEND_PORT:-18000}"
AGENT_ID="${TELEGRAM_AGENT_ID:-7296000000961828}"
AGENT_NAME="${TELEGRAM_AGENT_NAME:-Kas M}"
AGENT_TZ="${TELEGRAM_TIMEZONE:-America/Los_Angeles}"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN argument is required" >&2
  exit 1
fi
if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "ERROR: $APP_DIR is not a git repo (expected the project)" >&2
  exit 1
fi

cd "$APP_DIR"
echo "--- Step 1: pulling latest backend code (selective; won't touch docker-compose.yml) ---"
/usr/bin/git fetch origin main --quiet
/usr/bin/git checkout origin/main -- \
  backend/db.py \
  backend/main.py \
  backend/routers/telegram.py \
  backend/telegram_alerts.py \
  .env.example
/usr/bin/git log --oneline origin/main -1

echo "--- Step 2: setting Telegram env vars in .env ---"
ENV_FILE="$APP_DIR/.env"
touch "$ENV_FILE"
/usr/bin/sed -i '/^TELEGRAM_/d' "$ENV_FILE"
{
  echo ""
  echo "TELEGRAM_BOT_TOKEN=${TOKEN}"
  echo "TELEGRAM_AGENT_ID=${AGENT_ID}"
  echo "TELEGRAM_AGENT_NAME=${AGENT_NAME}"
  echo "TELEGRAM_TIMEZONE=${AGENT_TZ}"
} >> "$ENV_FILE"
echo "current TELEGRAM_* lines in .env:"
/usr/bin/grep -E '^TELEGRAM_' "$ENV_FILE" | /usr/bin/sed 's/=.*/=***hidden***/'

echo "--- Step 3: rebuilding backend container ---"
/usr/bin/docker compose up -d --build --no-deps backend
echo "waiting 30s for backend to settle..."
sleep 30

echo "--- Step 4: verifying /api/telegram/status ---"
/usr/bin/curl -sS --max-time 15 "http://127.0.0.1:${BACKEND_PORT}/api/telegram/status" || true
echo
echo "--- Step 5: tail of backend logs ---"
/usr/bin/docker logs --tail 25 zoho_analytics_backend 2>&1 || true

echo "--- Telegram bot deploy finished ---"
