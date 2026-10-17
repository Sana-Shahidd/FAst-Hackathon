#!/usr/bin/env bash
# Write the 6 secrets a Hugging Face Space needs from your local .env into ./space_secrets.txt (gitignored).
# Nothing is printed. In the Space: Settings -> Variables and secrets -> "New secret", one per line (name = left of "=").
# Everything else (APP_ENV, model ids, cookies, PUBLIC_BASE_URL via SPACE_HOST) has a default in the Dockerfile/config.
set -euo pipefail
[ -f .env ] || { echo ".env not found (run from the repo root)"; exit 1; }
get() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed 's/^"//;s/"$//'; }
SECRET="$(get SECRET_KEY)"
[ -n "$SECRET" ] || SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))' 2>/dev/null || python -c 'import secrets;print(secrets.token_urlsafe(48))')"
: > space_secrets.txt
printf 'SECRET_KEY=%s\n' "$SECRET" >> space_secrets.txt
for KEY in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY GEMINI_API_KEY GROQ_API_KEY; do
  VALUE="$(get "$KEY")"
  if [ -n "$VALUE" ]; then printf '%s=%s\n' "$KEY" "$VALUE" >> space_secrets.txt; else echo "! $KEY is empty in .env, skipped"; fi
done
echo "✓ wrote space_secrets.txt ($(wc -l < space_secrets.txt) lines). Add each as a Space secret, then delete the file."
