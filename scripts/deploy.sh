#!/usr/bin/env bash
# Usage: scripts/deploy.sh [sha]
# Needs APP_URL (public https URL of the service).
# - With the Railway CLI + RAILWAY_TOKEN (or a logged-in CLI): uploads and deploys this checkout (`railway up`).
# - Otherwise (Railway's own GitHub deploy is connected): only waits for that deploy to report this commit.
# RAILWAY_SERVICE defaults to "subah".
set -euo pipefail
SHA="${1:-$(git rev-parse HEAD)}"
: "${APP_URL:?missing APP_URL}"
APP_URL="${APP_URL%/}"
SERVICE="${RAILWAY_SERVICE:-subah}"

if command -v railway >/dev/null 2>&1 && { [ -n "${RAILWAY_TOKEN:-}" ] || railway whoami >/dev/null 2>&1; }; then
  # `railway up` uploads files without git metadata: the image learns its commit from this file
  echo "$SHA" > app/VERSION
  trap 'rm -f app/VERSION' EXIT
  echo "▶ deploying ${SHA:0:7} to Railway service '$SERVICE'"
  railway up --ci --service "$SERVICE"
else
  echo "▶ no Railway CLI login: waiting for Railway's GitHub deploy of ${SHA:0:7}"
fi

for i in $(seq 1 60); do
  V="$(curl -fsS "$APP_URL/health" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
  if [ "$V" = "$SHA" ]; then echo "✓ live: $APP_URL (${SHA:0:7})"; exit 0; fi
  sleep 10
done
echo "✗ new version not live after 10 min (current: ${V:-unreachable})"; exit 1
