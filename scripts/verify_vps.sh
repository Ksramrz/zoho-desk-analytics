#!/usr/bin/env bash
# Aggregate status report for the VPS deploy. Writes to a path I can curl.
# Usage: bash /tmp/verify_vps.sh

set -uo pipefail

OUT="/tmp/roomvu_status.txt"
PUB_DIR=""

# Find a publicly served nginx webroot (try common candidates).
for candidate in \
  /var/www/html \
  /var/www/cashvers/public_html \
  /var/www/cashvers \
  /home/cashvers/public_html \
  /var/www/cashvers.com/public_html \
  /var/www/cashvers.com; do
  if [[ -d "$candidate" ]]; then
    PUB_DIR="$candidate"
    break
  fi
done

{
  echo "=== roomvu vps verify $(date -u +%FT%TZ) ==="
  echo
  echo "--- docker ---"
  command -v docker && docker --version || echo "docker MISSING"
  echo
  echo "--- compose ps in /opt/zoho-desk-analytics ---"
  if [[ -d /opt/zoho-desk-analytics ]]; then
    (cd /opt/zoho-desk-analytics && docker compose ps 2>&1) || true
  else
    echo "/opt/zoho-desk-analytics MISSING"
  fi
  echo
  echo "--- listening ports ---"
  ss -tlnp 2>&1 | head -n 40 || true
  echo
  echo "--- backend health (loopback) ---"
  curl -sS --max-time 5 http://127.0.0.1:18000/api/health || echo "backend not responding"
  echo
  echo "--- metabase index (loopback) ---"
  curl -sS --max-time 5 -o /dev/null -w 'metabase http %{http_code}\n' http://127.0.0.1:13000/ || echo "metabase not responding"
  echo
  echo "--- frontend index (loopback) ---"
  curl -sS --max-time 5 -o /dev/null -w 'frontend http %{http_code}\n' http://127.0.0.1:18080/ || echo "frontend not responding"
  echo
  echo "--- nginx sites-enabled ---"
  ls -1 /etc/nginx/sites-enabled/ 2>&1 || true
  echo
  echo "--- nginx test ---"
  nginx -t 2>&1 || true
  echo
  echo "--- last 50 lines of /var/log/roomvu-deploy.log ---"
  tail -n 50 /var/log/roomvu-deploy.log 2>&1 || echo "deploy log missing"
  echo
  echo "--- pub_dir ---"
  echo "PUB_DIR=$PUB_DIR"
} > "$OUT" 2>&1

# Also publish to webroot if found, to make it externally fetchable.
if [[ -n "$PUB_DIR" ]]; then
  cp "$OUT" "$PUB_DIR/roomvu_status.txt"
  chmod 0644 "$PUB_DIR/roomvu_status.txt" || true
  echo "Published to $PUB_DIR/roomvu_status.txt"
else
  echo "No webroot found; status only in $OUT"
fi

# Try common webroot via default nginx 187.77.103.56 alias too.
if [[ -d /var/www/html ]]; then
  cp "$OUT" /var/www/html/roomvu_status.txt
  chmod 0644 /var/www/html/roomvu_status.txt || true
fi

echo "Wrote $OUT"
echo "FINGERPRINT:$(date +%s)"
