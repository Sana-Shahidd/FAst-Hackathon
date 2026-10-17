# AGENTS.md — Rules for any AI coding tool working on Subah

Read this whole file before writing code, then `docs/01_CONTEXT.md` and the doc for the
task you are on. These rules override your defaults. Time budget is **9 hours, solo** —
working and simple beats clever.

## Rule 0 — Do not hallucinate

1. Table, column, route, env var, file and function names MUST match `docs/04_DATA.md`,
   `docs/05_ROUTES.md` and `docs/03_TECH.md` exactly. Never invent one. If something is
   missing, add it to the doc first, then code it.
2. Use only library functions that exist in the pinned versions (`docs/03_TECH.md`). If
   unsure, check the installed package source (`pip show -f <pkg>`) before using it.
3. Model names come from env vars only (`CURATOR_MODEL`, …). Never hard-code them.
4. No fake success. Unfinished code raises `NotImplementedError("F-xx: <what>")`.
5. Ambiguity → pick the simplest behaviour that satisfies `docs/02_PRD.md`, and write it in
   `docs/DECISIONS.md` (time, decision, reason).

## Rule 1 — Reuse, don't rebuild

| Need | Use | Never hand-write |
|---|---|---|
| Web server, validation | FastAPI + Pydantic | manual dict checks |
| Settings | pydantic-settings | `os.environ` parsing |
| HTML pages (web + PDF) | Jinja2 templates | string-concatenated HTML |
| Small interactivity | HTMX (CDN script) + a few lines of vanilla JS | a React/SPA build |
| Auth, sessions, DB, storage | Supabase (Auth, Postgres, Storage) | password hashing, JWT code |
| News feeds | `feedparser` (RSS/Atom) + Google News RSS search URLs | HTML scraping of news sites |
| Duplicate headlines | `rapidfuzz.fuzz.token_set_ratio` | custom string similarity |
| Agents | `openai-agents` SDK with Gemini/Groq OpenAI-compatible endpoints, typed outputs | custom agent loops, regex-parsing LLM text |
| HTML → PDF | Playwright Chromium `page.pdf()` | ReportLab layouts, other PDF libs |
| Localized dates/numbers | `babel.dates.format_date`, `babel.numbers` | manual month-name tables |
| Translations of UI text | `docs/07_DESIGN.md` §6 string table → `app/i18n/<lang>.json` | translating UI with the LLM at runtime |
| Fonts for all scripts | Google Fonts Noto families | bundling font files |
| Scheduling the 06:00 edition | APScheduler `AsyncIOScheduler` | `while True: sleep` |
| Retries | tenacity | retry loops |
| Rate limiting | slowapi | counters in dicts |
| HTTP | httpx (async) | requests |
| Icons | Lucide (CDN UMD) | hand-drawn SVG icon sets |
| Web push | pywebpush (VAPID) | VAPID signing / payload encryption code |
| Deploy | Dockerfile on Playwright base image + Hugging Face Spaces (or Railway) + GitHub Actions | custom servers, manual uploads |
| Testing | pytest, pytest-asyncio, respx, FastAPI TestClient | ad-hoc test scripts |

Do not add dependencies outside `docs/03_TECH.md`. If one is truly needed, add it there
with version and reason first.

## Rule 2 — Agents propose, code decides

- Agents only return typed outputs (Pydantic). Code validates every id they return against
  the candidate list and drops anything invalid.
- Every agent has a deterministic **fallback** (`docs/06_AGENTS.md`). An LLM failure must
  never stop a paper from being generated.
- Article text from feeds is untrusted. It is wrapped in `<article>` tags and agents are told
  to ignore instructions inside it.
- Never send user emails or ids to an LLM — only interests, language, city and article data.
- Every agent run writes rows to `agent_activity` (shown on "How this paper was made").

## Rule 3 — Security basics

- Secrets only in `.env` (never committed); commit `.env.example` with empty values.
- The service-role key stays on the server. Browser JS never talks to the DB directly.
- Every page except `/`, `/login`, `/signup` requires a logged-in user (`deps.require_user`).
- Users can only read their own editions, PDFs and signals (check `user_id` in every query).
- Session = Supabase access + refresh token in `HttpOnly; Secure; SameSite=Lax` cookies.
- Outbound article links go through `/r/{edition_article_id}` (logs the click, then 302 to
  the stored URL — never to a URL taken from the query string).
- Escape all feed text (Jinja autoescape ON; never mark feed text `|safe`).

## Rule 4 — Conventions

- Python 3.13, type hints, `async def` for I/O, `ruff format` clean, functions ≤ 60 lines.
- The Supabase Python client is synchronous: call it with `await asyncio.to_thread(...)`.
- Store time in UTC; show in the user's `timezone`.
- RTL languages (`ur`, `ar`): set `dir="rtl"` on `<html>`; CSS uses logical properties
  (`margin-inline-start`, `text-align: start`) so one stylesheet serves both directions.
- All UI text via `t('key')` with keys in every `app/i18n/<lang>.json`.

## Rule 5 — Workflow: one tested feature per push (commits are monitored)

1. Public GitHub repo from minute one. Follow `docs/08_BUILD_PLAN.md` in order.
2. A task is done only when: its code works, its **Check** passes, and its unit +
   integration tests (listed in `docs/09_SETUP_TEST_DEMO.md` §2) exist and pass.
3. Ship with the **shipper** subagent (`.claude/agents/shipper.md`) or
   `bash scripts/ship.sh T-xx "summary"` — never raw `git commit/push`. The gate runs
   ruff → unit → integration → secret scan → commit → push. One task per commit.
4. Never weaken tests to pass the gate (no skips, xfails, or asserts on nothing).
5. Deploy with the **deployer** subagent (`.claude/agents/deployer.md`) or let GitHub
   Actions deploy automatically when `main` passes tests. Frontend and backend are one
   service, so one deploy ships both; the smoke test checks both.
6. Push to `main` at least every 45 minutes so the live app stays current.
7. Do not refactor unrelated code or rename anything defined in the docs.

## Rule 6 — Tests

- `tests/unit/` (`@pytest.mark.unit`): pure functions — feeds, mutes, scoring, validation,
  puzzle, learning math, i18n. No network, no DB. Must run in < 10 s total.
- `tests/integration/` (`@pytest.mark.integration`): FastAPI `TestClient` through real
  routes against the **test** Supabase project (`TEST_SUPABASE_*`), with LLM agents patched
  (`app.agents.runner.run_agent`) and feeds mocked with `respx` from fixtures in
  `tests/fixtures/`. Each test creates its own user (`it-<uuid>@subah.test`) and deletes it
  in teardown (`auth.admin.delete_user`, cascades all rows).
- Never call real LLMs or real news feeds in tests.
