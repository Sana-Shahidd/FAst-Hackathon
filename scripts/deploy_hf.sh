#!/usr/bin/env bash
# Deploy to a Hugging Face Space (Docker SDK) by pushing this commit to the Space's git repo.
#
#   HF_TOKEN=hf_xxx HF_SPACE=owner/space bash scripts/deploy_hf.sh [git-ref]
#
# HF_TOKEN: a "write" access token (huggingface.co/settings/tokens). It is only sent to huggingface.co.
# The Space builds the Dockerfile and serves it at https://<owner>-<space>.hf.space (port 7860, README front matter).
# `app/VERSION` is added to the pushed commit so /health reports the commit (a Space has no git metadata).
set -euo pipefail
: "${HF_TOKEN:?missing HF_TOKEN}"; : "${HF_SPACE:?missing HF_SPACE (owner/space)}"
REF="${1:-HEAD}"
SHA="$(git rev-parse "$REF")"
APP_URL="https://$(echo "$HF_SPACE" | tr '/_A-Z' '--a-z').hf.space"
[ -n "${GITHUB_ENV:-}" ] && echo "APP_URL=$APP_URL" >> "$GITHUB_ENV"

DIR="$(mktemp -d)"
git worktree add -q --detach "$DIR/w" "$SHA"
cleanup() { git worktree remove --force "$DIR/w" >/dev/null 2>&1 || true; rm -rf "$DIR"; }
trap cleanup EXIT
(
  cd "$DIR/w"
  echo "$SHA" > app/VERSION
  git add -f app/VERSION
  git -c user.name="subah-deploy" -c user.email="deploy@subah.local" commit -q -m "deploy ${SHA:0:7}"
  AUTH="$(printf 'hf:%s' "$HF_TOKEN" | base64 | tr -d '\n')"
  echo "▶ pushing ${SHA:0:7} to huggingface.co/spaces/$HF_SPACE"
  git -c "http.extraHeader=Authorization: Basic $AUTH" -c http.version=HTTP/1.1 \
    push --force "https://huggingface.co/spaces/$HF_SPACE" HEAD:main
)

echo "▶ waiting for the Space to build and report ${SHA:0:7} at $APP_URL (up to 20 min)"
for i in $(seq 1 120); do
  V="$(curl -fsS "$APP_URL/health" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
  if [ "$V" = "$SHA" ]; then echo "✓ live: $APP_URL (${SHA:0:7})"; exit 0; fi
  sleep 10
done
echo "✗ the Space did not report ${SHA:0:7} in time (current: ${V:-unreachable}); check its Logs tab"; exit 1
