# PROGRESS — read this first if you are picking the project up mid-build

Last updated: 2026-10-17 ~12:15 (local). Demo deadline: **8 pm today**. Repo:
https://github.com/Sana-Shahidd/FAst-Hackathon (branch `main`). Working dir:
`C:\Users\mobee\Downloads\subah-docs\subah`.

If you are an AI coding tool taking over: read `AGENTS.md`, `CLAUDE.md`, `docs/00_README.md`, then this
file, then `docs/DECISIONS.md` (every deviation from the docs is logged there). Follow
`docs/08_BUILD_PLAN.md` task by task; never invent names that are not in `docs/`.

## Overall: about 18% of the 9-hour plan done (T-01…T-03 complete, T-04 half)

| Task | What | State | Commit |
|---|---|---|---|
| T-01 | Repo, `/health`, i18n service, CI/Docker files | **Done** (CI/Render deploy never confirmed green, see Deploy) | `8ec860e`, `b446dcf` |
| T-02 | `config.py`, `agents/llm.py`, `runner.py`, `smoke.py`, VAPID script | **Done**, `python -m app.agents.smoke` ok for all models | `66c828e` (+ model ids pending commit) |
| T-03 | Feeds, mute filter, source catalog, custom feed validation, `feeds.json` | **Done**, live Check passed (261 en / 195 ur candidates) | `9c5904d` |
| T-04 | Layout, language/RTL, CSRF, sessions, landing/login/signup | **Part 1 done**; **part 2 blocked** (needs Supabase) | `ccc7ed0` |
| T-05 | Onboarding (5 steps, Profiler agent, `POST /onboarding`) | Not started | |
| T-06 | Edition pipeline (Curator, Editor, fallbacks, puzzle items, layout) | Not started | |
| T-07 | Home view, article sheet, `/r/{id}`, signals, read marks, save | Not started | |
| T-08 | Paper view + PDF (Playwright) | Not started | |
| T-09 | Archive, Saved tab, regenerate, `/dev/time-travel` | Not started | |
| T-10 | Learning weights, Learner agent, profile page | Not started | |
| T-11 | Headline puzzle page | Not started | |
| T-12 | Reading comfort, push notification, scheduler, settings | Not started | |
| T-13 | City section, making-of, Three Things, language switch | Not started | |
| T-14 | Hardening, rate limits, seed demo data, production checks | Not started | |
| T-15 | Architecture diagram, README screenshots, Loom, submit | Not started | |

**Minimum for a believable 8 pm demo:** T-04 part 2 → T-05 → T-06 → T-07 (sign up, onboard, get a real
paper, read it). Then T-08 (PDF), T-09 (archive), T-10 (learning). Cut order is in `08_BUILD_PLAN.md`.

## What exists now (all on `main`, 72 unit + 40 integration tests green)

- `app/main.py` (`create_app()` factory, `/health` with a real DB check), `app/config.py`, `app/deps.py`
  (Supabase clients, `render()`, CSRF, cookies + refresh, `require_user`, slowapi limiter),
  `app/models.py` (`Profile`, `Interest`, `FavoriteSource`, `FeedUrl`, `Candidate`).
- `app/services/`: `i18n.py`, `feeds.py`, `mutes.py`, `sources.py`, `activity.py`.
- `app/agents/`: `llm.py`, `runner.py` (`run_agent`: primary → fallback model → `None`), `smoke.py`.
- `app/routers/auth.py` (landing, signup, login, logout) and `routers/paper.py` (placeholder:
  `/paper/today` requires login then raises `NotImplementedError("F-07 …")`).
- Templates: `base.html`, `landing.html`, `login.html`, `signup.html`, `_auth_form.html`,
  `_lang_chips.html`, `_bottom_nav.html`, `error.html`. Static: `app.css` (navy/maroon tokens, theme-aware
  role tokens `--primary/--link/--alert-ink`), `app.js`, `favicon.svg`.
- Data: `app/data/feeds.json` (verified live), 128 i18n keys × 8 languages (7 added in T-04).

## Blockers needing the human (nothing here can be done by the coding tool)

1. **Supabase project `yjnmfpwrwzhqqgmswrbe`** (URL + publishable key are in `.env`):
   - run `supabase/schema.sql` in the SQL editor (currently **no tables exist**);
   - Authentication → Providers → Email: turn **"Confirm email" OFF** (currently on, so signups return no session);
   - Project Settings → API Keys: copy the **secret / service-role key** into `SUPABASE_SERVICE_ROLE_KEY`
     **and** `TEST_SUPABASE_SERVICE_ROLE_KEY` in `.env`. (The test keys currently point at the same project;
     create a separate test project later if time allows.)
2. **Render** deploy: unconfirmed. The first image failed (`playwright/python:v1.64.0-noble` does not exist);
   fixed by pinning 1.63.0 in `b446dcf`. The `onrender.com` URL was never confirmed (`subah.onrender.com`
   is someone else's Express app). Deployment is parked by the user's choice.
3. A Gemini key and a Groq key were pasted into the chat; consider rotating them after the demo.

## Environment & workflow gotchas (Windows, this machine)

- Python venv: `.venv/Scripts/python` (3.13). Run tests as
  `.venv/Scripts/python -m pytest -m unit -q` and `… -m integration -q`. The venv `*.exe` shims are blocked
  by Windows Application Control, and bare `ruff`/`pytest` on PATH are an unpinned Python 3.12 (ruff 0.15).
- Ship a task (lint → unit → integration → secret scan → commit → push) with the **shipper** subagent, or:
  `PATH="$PWD/.venv/shims:$PATH" bash scripts/ship.sh T-xx "summary"` (`.venv/shims/{pytest,ruff}` are
  gitignored wrappers that call `python -m`). Never raw `git commit/push`. One task per commit.
- Lint is **ruff 0.17.1 with its stricter defaults** (B008, BLE001, UP033, I001…). Use
  `Annotated[T, Depends(...)]`, and `# noqa: BLE001 - reason` on deliberate broad `except Exception`.
- Unit tests take ~8 s (the `openai-agents` import alone is ~4 s here); limit is 10 s.
- Use the Write tool, not bash heredocs, for files containing Urdu/Arabic/Hindi text.
- Dev server: `.claude/launch.json` (`uvicorn app.main:app --port 8000`).
- `.env` is gitignored and holds real keys. Never print or commit its values.

## Findings that contradict the docs (details in DECISIONS.md)

- **Google News has no Urdu edition** (`hl=ur` redirects to English). Native Urdu comes from curated feeds in
  `feeds.json`; `Candidate.lang` is detected from the headline's script (`feeds.detect_lang`).
- Model ids (verified by smoke): `PROFILER`/`LEARNER` = `gemini:gemini-3.1-flash-lite`,
  `CURATOR`/`EDITOR` = `gemini:gemini-2.5-flash`, `FALLBACK` = `groq:qwen/qwen3.8-27b`.
  (`gemini-2.5-flash-lite` closed to new users; Groq `gpt-oss-*` fail typed-output JSON validation.)
- T-04 was split in two because no Supabase existed; part 2 = `integration/test_auth.py` and
  `test_auth_scope.py` against the real test project (required by `09_SETUP_TEST_DEMO.md` §2).
- UI strings added by me in ur/ar/hi/bn/es/fr/zh need a native-speaker glance before the demo.

## Next steps, in order

1. (Human) finish the Supabase blockers above, then tell the tool "Supabase is ready".
2. Ship T-04 part 2: write `tests/integration/test_auth.py` (signup → profile row; login sets cookies; logout
   clears; wrong-password message) and `test_auth_scope.py` skeleton with the real `it-<uuid>@subah.test`
   user fixture (`auth.admin.create_user(..., email_confirm=True)`, deleted in teardown); fill the `user`
   fixture in `tests/conftest.py`.
3. T-05 onboarding → T-06 edition pipeline → T-07 home view (see `08_BUILD_PLAN.md`, `05_ROUTES.md`,
   `06_AGENTS.md`, `07_DESIGN.md`). `ProfilerOut`/`CuratorOut`/`EditorOut`/`LearnerOut` go in `app/models.py`
   exactly as in `06_AGENTS.md` §3.
4. Keep `docs/DECISIONS.md` and this file updated after every shipped task.
