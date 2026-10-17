#!/usr/bin/env bash
# Prepare the app settings for Railway from your local .env. Nothing is printed.
#
#   bash scripts/railway_env.sh https://<service>.up.railway.app [APP_ENV] [--cli]
#
# Default: writes ./railway.env (gitignored) with KEY=VALUE lines. Open it, copy everything, and paste it into
#   Railway -> your service -> Variables -> RAW Editor -> Update Variables. Delete railway.env afterwards.
# With --cli: sets the variables directly through the Railway CLI (`railway login` + `railway link` first).
#
# APP_ENV defaults to "production". Use "dev" if the live demo needs the time-travel button.
set -euo pipefail
URL="${1:?public https URL of the Railway service}"
APP_ENV_VALUE="${2:-production}"
[ "$APP_ENV_VALUE" = "--cli" ] && APP_ENV_VALUE="production"
MODE=file; for arg in "$@"; do [ "$arg" = "--cli" ] && MODE=cli; done
SERVICE="${RAILWAY_SERVICE:-subah}"
[ -f .env ] || { echo ".env not found (run from the repo root)"; exit 1; }

get() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed 's/^"//;s/"$//'; }

SECRET="$(get SECRET_KEY)"
[ -n "$SECRET" ] || SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))' 2>/dev/null || python -c 'import secrets;print(secrets.token_urlsafe(48))')"

PAIRS=("APP_ENV=$APP_ENV_VALUE" "SESSION_COOKIE_SECURE=true" "PUBLIC_BASE_URL=${URL%/}" "SECRET_KEY=$SECRET")
for KEY in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY GEMINI_API_KEY GROQ_API_KEY \
           PROFILER_MODEL CURATOR_MODEL EDITOR_MODEL LEARNER_MODEL FALLBACK_MODEL \
           VAPID_PUBLIC_KEY VAPID_PRIVATE_KEY VAPID_SUBJECT; do
  VALUE="$(get "$KEY")"
  if [ -n "$VALUE" ]; then PAIRS+=("$KEY=$VALUE"); else echo "! $KEY is empty in .env, skipped"; fi
done

if [ "$MODE" = cli ]; then
  ARGS=(); for P in "${PAIRS[@]}"; do ARGS+=(--set "$P"); done
  railway variables --service "$SERVICE" --skip-deploys "${ARGS[@]}" >/dev/null
  echo "✓ set ${#PAIRS[@]} variables on Railway service '$SERVICE' (APP_ENV=$APP_ENV_VALUE)"
else
  printf '%s\n' "${PAIRS[@]}" > railway.env
  echo "✓ wrote railway.env with ${#PAIRS[@]} variables (APP_ENV=$APP_ENV_VALUE). Paste it into Railway's RAW Editor, then delete it."
fi
