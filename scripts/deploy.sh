#!/usr/bin/env bash
# Usage: scripts/deploy.sh [sha]   (needs RENDER_DEPLOY_HOOK_URL, RENDER_APP_URL)
set -euo pipefail
SHA="${1:-$(git rev-parse origin/main)}"
: "${RENDER_DEPLOY_HOOK_URL:?missing}"; : "${RENDER_APP_URL:?missing}"
echo "▶ triggering deploy of ${SHA:0:7}"
curl -fsS -X POST "$RENDER_DEPLOY_HOOK_URL" >/dev/null
for i in $(seq 1 60); do
  V="$(curl -fsS "$RENDER_APP_URL/health" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
  if [ "$V" = "$SHA" ]; then echo "✓ live: $RENDER_APP_URL (${SHA:0:7})"; exit 0; fi
  sleep 10
done
echo "✗ new version not live after 10 min (current: ${V:-unreachable})"; exit 1
