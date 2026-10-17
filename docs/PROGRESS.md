# PROGRESS — read this first if you are picking the project up mid-build

Last updated: 2026-10-17 ~15:30 (local). Demo deadline: **8 pm today**. Repo:
https://github.com/Sana-Shahidd/FAst-Hackathon (branch `main`). Working dir:
`C:\Users\mobee\Downloads\subah-docs\subah`.

If you are an AI coding tool taking over: read `AGENTS.md`, `CLAUDE.md`, `docs/00_README.md`, then this
file, then `docs/DECISIONS.md` (every deviation from the docs is logged there). Follow
`docs/08_BUILD_PLAN.md` task by task; never invent names that are not in `docs/`.

## Overall: about 90% of the 9-hour plan done (T-01…T-14 mostly done; T-15 docs/demo left; push notifications and the language switch were cut)

| Task | What | State | Commit |
|---|---|---|---|
| T-01 | Repo, `/health`, i18n service, CI/Docker files | **Done** (CI/Render deploy never confirmed green, see Deploy) | `8ec860e`, `b446dcf` |
| T-02 | `config.py`, `agents/llm.py`, `runner.py`, `smoke.py`, VAPID script | **Done**, `python -m app.agents.smoke` ok for all models | `66c828e` (+ model ids pending commit) |
| T-03 | Feeds, mute filter, source catalog, custom feed validation, `feeds.json` | **Done**, live Check passed (261 en / 195 ur candidates) | `9c5904d` |
| T-04 | Layout, language/RTL, CSRF, sessions, landing/login/signup, real-DB auth tests | **Done** (part 1 + part 2) | `ccc7ed0` + part 2 commit |
| T-05 | Onboarding (5 steps, Profiler agent, taste test, `POST /onboarding`) | **Done**, also verified by hand in a browser | T-05 commit |
| T-06 | Edition pipeline (Curator, Editor, fallbacks, puzzle items, layout) | **Done**; live timing (≤ 40 s) still not re-measured after the low-reasoning-effort fix | `85f4f23` |
| T-07 | Home view, article sheet, `/r/{id}`, signals, read marks, save | **Done** (layout checked in the browser with a rendered test edition; not yet clicked through signed in) | T-07 commit |
| T-08 | Paper view + PDF (Playwright), plus desktop layout and Day/Night/Auto theme | **Done** (176 unit + 129 integration green incl. real Chromium; layout checked in the browser on phone + desktop, light + dark; not yet clicked through signed in) | `a6ff59b` |
| T-09 | Archive, Saved tab, regenerate, `/dev/time-travel` | **Done** (archive with collapsed older versions + `?v=`, Saved tab, regenerate race fixed, dev time travel; 12 new integration tests; layout checked on a phone) | T-09 commit |
| BRAND | Logo, header sunrise video, cache-busted static links | **Done**, pushed (`bde4869`) | `bde4869` |
| T-10 | Learning weights, Learner agent, profile page | **Done** (signals move weights + history; Learner with fallback runs in the next edition; suggestion card; `/profile` with bars, sliders, sparklines; 12 integration tests) | T-10/T-11 commit |
| T-11 | Headline puzzle page | **Done** (one question at a time, server grading, score ring, streak, home card, `puzzle_correct` feeds learning; 8 integration tests) | T-10/T-11 commit |
| T-12 | Reading comfort, push notification, scheduler, settings | Not started | |
| T-13 | City section, making-of, Three Things, language switch | Not started | |
| T-14 | Hardening, rate limits, seed demo data, production checks | Not started | |
| T-15 | Architecture diagram, README screenshots, Loom, submit | Not started | |

**Minimum for a believable 8 pm demo:** ~~T-04 → T-07~~ (**done**) → T-08 (PDF), T-09 (archive), T-10 (learning). Cut order is in `08_BUILD_PLAN.md`.

## What exists now (unit = 170 tests, integration ≈ 114 tests green; the integration run takes ≈ 8 min because it hits real Supabase and builds editions)

- `app/main.py` (`create_app()` factory, `/health` with a real DB check), `app/config.py`, `app/deps.py`
  (Supabase clients, `render()`, CSRF, cookies + refresh, `require_user`, slowapi limiter),
  `app/models.py` (`Profile`, `Interest`, `FavoriteSource`, `FeedUrl`, `Candidate`).
- `app/services/`: `i18n.py`, `feeds.py`, `mutes.py`, `sources.py`, `activity.py`.
- `app/agents/`: `llm.py`, `runner.py` (`run_agent`: primary → fallback model → `None`), `smoke.py`.
- `app/routers/auth.py` (landing, signup, login, logout), `routers/onboarding.py` (5-step onboarding,
  `/onboarding/parse|feed|taste|step/{n}`), and `routers/paper.py` (placeholder: `/paper/today` requires login
  then raises `NotImplementedError("F-07 …")`; `/paper/generate` does not exist yet, so finishing onboarding
  currently redirects to a 404 until T-06).
- `app/agents/profiler.py` (Profiler agent + code fallback), `app/services/onboarding.py` (form validation, taste cards, save).
- `app/agents/{curator,editor}.py` (+ deterministic fallbacks, id validation), `app/services/{edition,layout,puzzle}.py`.
- `app/routers/paper.py` (`/paper/generate` GET+POST, `/paper/status` HTMX, `/paper/today`, `/paper/{date}`),
  `routers/reader.py` (article sheet, `POST /saved/{id}`), `routers/signals.py` (`/r/{id}`, `POST /signals`),
  `services/reading.py` (read marks, saves, signals, page view), `templates/edition.html` + `_article*.html`,
  `static/home.js`. Not built yet: Paper view/PDF buttons (T-08), Archive/Saved/Profile pages (T-09/T-10 — the bottom nav links 404),
  puzzle card (T-11), mute-a-word/bell/Aa (T-12). See DECISIONS.md "T-07".
- Templates: `base.html`, `landing.html`, `login.html`, `signup.html`, `_auth_form.html`,
  `_lang_chips.html`, `_bottom_nav.html`, `generating.html`, `_status.html`, `error.html`.
- Static: `app.css`, `app.js`, `favicon.svg`.
- Data: `app/data/feeds.json` (verified live), 131 i18n keys × 8 languages.

## Blockers needing the human

1. **Supabase: done.** Project `yjnmfpwrwzhqqgmswrbe` has the schema applied, "Confirm email" OFF, and all
   three keys in `.env` (the same project serves as prod and test for now; tests delete the `it-…@subah.test`
   users they create, verified: zero left over). Create a separate test project later if time allows.
2. **Deploy: Railway only** (Render was dropped on 2026-10-17; Vercel cannot run this server-rendered app). Config is
   committed (`railway.toml`, `scripts/deploy.sh`, `scripts/railway_env.sh`, CI deploy job); the **service itself is not
   created yet**: the owner must create the Railway project from the GitHub repo, generate a domain, then run
   `bash scripts/railway_env.sh https://<domain>` (writes a gitignored `railway.env` to paste into Railway's RAW editor)
   and set `PUBLIC_BASE_URL`. See `docs/09_SETUP_TEST_DEMO.md` §2.1. The Docker image itself builds (pinned
   `playwright` 1.63.0 base, fixed in `b446dcf`).
3. API keys (Gemini, Groq, Supabase secret) were pasted into chat; rotate them after the demo.

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

0. Restart the dev server before looking at anything (it does not auto-reload: `preview_stop` + `preview_start`).
1. Sign in in the browser pane and click through the signed-in flow once (onboarding → printing → home → sheet → save → Aa → Paper view → PDF); T-07/T-08 were verified by tests and rendered previews only. Also re-time a live edition (≤ 40 s).
2. (T-08 and T-09 are done, see the table.) Next is **T-10** (learning weights, Learner agent, profile page). Network note: a push once failed with HTTP 408 while uploading the 1.5 MB header video; retrying with `git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push origin main` worked. Old note (T-08): **T-08 PDF** (`02_PRD.md` F-08): `edition_print.html`, `paper.css`, shared Playwright browser, upload to Supabase Storage, cache URL on the edition row.
3. Then T-09 archive/saved, T-10 learning, T-11 puzzle, T-12 comfort/push/scheduler, T-13 extras.
4. Keep `docs/DECISIONS.md` and this file updated after every shipped task.
