#!/usr/bin/env bash
# Usage: scripts/ship.sh T-07 "web edition"
# Gate: lint -> unit -> integration -> secret scan -> commit -> push. Stops on first failure.
set -euo pipefail
TASK="${1:?task id, e.g. T-07}"; SUMMARY="${2:?short summary}"
BRANCH="$(git symbolic-ref --short HEAD)"   # works on an unborn branch (first commit)

echo "▶ 1/5 lint"
ruff check app tests
ruff format --check app tests

echo "▶ 2/5 unit tests"
pytest -m unit -q

echo "▶ 3/5 integration tests"
pytest -m integration -q

echo "▶ 4/5 secret scan"
git add -A
if git diff --cached --name-only | grep -E '(^|/)\.env$' >/dev/null; then
  echo "✗ .env is staged — remove it"; git reset -q; exit 1; fi
if git diff --cached -U0 | grep -E '^\+' | grep -E 'eyJ[A-Za-z0-9_-]{30,}\.|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{20,}' >/dev/null; then
  echo "✗ possible secret in staged changes — move it to .env"; git reset -q; exit 1; fi

echo "▶ 5/5 commit + push ($BRANCH)"
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -q -m "$TASK: $SUMMARY

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push -q origin "$BRANCH"
echo "✓ shipped $(git rev-parse --short HEAD) to $BRANCH"
