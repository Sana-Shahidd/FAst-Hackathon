#!/usr/bin/env bash
# Usage: scripts/smoke.sh https://subah.onrender.com   (optional SMOKE_EMAIL / SMOKE_PASSWORD)
set -uo pipefail
U="${1:?base url}"; FAIL=0; JAR="$(mktemp)"
ok(){ echo "✓ $1"; }; bad(){ echo "✗ $1"; FAIL=1; }
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }

H="$(curl -fsS "$U/health" || true)"
echo "$H" | grep -q '"ok": *true'  && ok "health ok"  || bad "health: $H"
echo "$H" | grep -q '"db": *true'  && ok "database"   || bad "database"
echo "$H" | grep -q '"pdf": *true' && ok "pdf engine" || bad "pdf engine"
[ "$(code "$U/")" = 200 ]                && ok "landing page"   || bad "landing page"
[ "$(code "$U/login")" = 200 ]           && ok "login page"     || bad "login page"
[ "$(code "$U/static/app.css")" = 200 ]  && ok "static css"     || bad "static css"
[ "$(code "$U/sw.js")" = 200 ]           && ok "service worker" || bad "service worker"
[ "$(code "$U/paper/today")" = 303 ] || [ "$(code "$U/paper/today")" = 302 ] && ok "auth redirect" || bad "auth redirect"

if [ -n "${SMOKE_EMAIL:-}" ] && [ -n "${SMOKE_PASSWORD:-}" ]; then
  TOKEN="$(curl -s -c "$JAR" "$U/login" | grep -o 'name="csrf_token" value="[^"]*"' | sed 's/.*value="//;s/"$//')"
  curl -s -b "$JAR" -c "$JAR" -o /dev/null -X POST "$U/login" \
    --data-urlencode "email=$SMOKE_EMAIL" --data-urlencode "password=$SMOKE_PASSWORD" --data-urlencode "csrf_token=$TOKEN"
  [ "$(code -b "$JAR" -L "$U/paper/today")" = 200 ] && ok "today's paper" || bad "today's paper"
  TODAY="$(date -u +%F)"
  CT="$(curl -s -b "$JAR" -o /tmp/smoke.pdf -w '%{content_type}' "$U/paper/$TODAY/pdf")"
  SIZE="$(wc -c </tmp/smoke.pdf)"
  [[ "$CT" == application/pdf* ]] && [ "$SIZE" -gt 20000 ] && ok "pdf download (${SIZE} bytes)" || bad "pdf download ($CT, $SIZE bytes)"
fi
rm -f "$JAR"; exit $FAIL
