# 09 — Setup, Tests and Demo: Subah

## 1. Setup

1. **Supabase** → new project → SQL editor → run `supabase/schema.sql`. Authentication →
   Providers → Email ON, "Confirm email" OFF. Settings → API: copy URL, anon key, service role key.
2. **Google AI Studio** → API key; note a current free Flash and Flash-Lite model id.
3. **Groq console** → API key; note a current free instruction model id.
4. Local:
```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # fill values; SECRET_KEY = python -c "import secrets;print(secrets.token_urlsafe(48))"
python -m app.agents.smoke  # every model ok?
uvicorn app.main:app --reload --port 8000
```
5. Demo from a phone: `cloudflared tunnel --url http://localhost:8000` → set
   `PUBLIC_BASE_URL` to the https URL and `SESSION_COOKIE_SECURE=true`, restart.

## 2. Tests (`tests/`)

Two layers, both required before a feature ships (`AGENTS.md` Rule 5–6):
- **Unit** (`tests/unit/`, `@pytest.mark.unit`): pure functions, no network/DB, < 10 s total.
- **Integration** (`tests/integration/`, `@pytest.mark.integration`): FastAPI `TestClient`
  through real routes and the real **test** Supabase project; agents patched via
  `monkeypatch.setattr("app.agents.runner.run_agent", fake)`; feeds mocked with `respx`
  serving `tests/fixtures/*.xml`; Playwright real (PDF). Each test makes its own user
  `it-<uuid>@subah.test` with `auth.admin.create_user(..., email_confirm=True)` and deletes it
  in teardown.

`tests/conftest.py` fixtures: `client` (TestClient), `user` (created + logged-in cookies,
deleted after), `onboarded_user` (profile + 5 interests + 2 favorites + 1 mute),
`edition` (generated with fake agent outputs), `feeds_mock` (respx router), `fake_agents`
(returns fixed `CuratorOut`/`EditorOut`/`LearnerOut`/`ProfilerOut`, or `None` to force fallback).

| File | Layer | What it proves |
|---|---|---|
| `test_i18n.py` | unit | all 8 JSON files share identical keys; `t()` formats; rtl for ur/ar; babel full date per locale |
| `test_runner_fallback.py` | unit | primary model error → fallback model; both fail → `None`; activity rows written |
| `test_feeds.py` | unit | Google News URL per language; fixture normalisation; HTML stripped; dedupe ≥ 85; recent-title exclusion |
| `test_mutes.py` | unit | word-boundary match ("ai" doesn't mute "said"); case-insensitive; `zh` substring; removed count |
| `test_sources.py` | unit | catalog = native first then English; custom URL validation (non-http rejected; bozo + 0 entries rejected; good fixture accepted) |
| `test_profiler_fallback.py` | unit | comma/"and"/"،"/"و" split → ≤ 5 interests |
| `test_curator_fallback.py` | unit | scoring incl. favorite ×1.25; max 3/section, 2/source; blocked never picked; one lead; ≥ 1 favorite when fresh |
| `test_agent_validation.py` | unit | unknown ids dropped + topped up; Editor gaps filled by fallback; lengths enforced |
| `test_puzzle.py` | unit | valid Editor items kept; invalid (answer in decoys, headline mismatch) replaced; fallback picks non-stopword ≥ 4 letters; always 5 items; grading |
| `test_reading.py` | unit | read ids from signals; saved toggle logic |
| `test_learning.py` | unit | every signal kind incl. `save`, `puzzle_correct` changes weight by its constant; clamps; history row |
| `test_learner_fallback.py` | unit | topic with ≥ 3 likes not in interests → suggestion |
| `test_push.py` | unit | payload shape; 410 response deletes subscription; no subscription → 0 sent |
| `test_health.py` | integration | `/health` returns ok, db, pdf, version |
| `test_auth.py` | integration | signup → profile row; login sets cookies; logout clears; wrong password message |
| `test_auth_scope.py` | integration | user A gets 404 for user B's paper, PDF, `/r/`, saved, puzzle |
| `test_onboarding.py` | integration | full POST creates profile, interests (weights from levels + taste), favorites, mutes |
| `test_generate_edition.py` | integration | mocked feeds + fake agents → edition ready, slots, puzzle (5), muted story absent, favorite story present; with agents `None` → fallback edition still ready |
| `test_edition_page.py` | integration | home renders hero, sources row, sections, read ticks, puzzle card |
| `test_signals.py` | integration | 👍/👎/hide source/dwell beacon recorded and weights updated |
| `test_redirect.py` | integration | `/r/{id}` 302s only to stored URL; records click → card shows ✓ |
| `test_pdf.py` | integration | PDF bytes start with `%PDF`, > 20 KB, cached second time (no re-render), Urdu edition renders |
| `test_archive_saved.py` | integration | archive lists editions; save/unsave; saved page grouped |
| `test_learning_flow.py` | integration | likes → learner (fake) → suggestion card → accept → interest added |
| `test_puzzle_flow.py` | integration | answer 5 questions → score, streak, `puzzle_correct` signals |
| `test_settings_push.py` | integration | comfort saved and applied as `data-*` attrs; subscribe/unsubscribe; `send_ready` called after scheduled edition (pywebpush mocked) |
| `test_making_of.py` | integration | timeline shows pipeline/curator/editor rows incl. a fallback |

Run locally: `pytest -m unit -q` and `pytest -m integration -q` (needs `TEST_SUPABASE_*`).

## 2.1 Ship and deploy
- **Ship a task:** ask Claude Code "use the shipper agent to ship T-07 web edition (F-07,
  F-19, F-22)" — or run `bash scripts/ship.sh T-07 "web edition"`.
- **Deploy:** pushing to `main` deploys automatically after CI tests pass. To deploy or
  re-check by hand: "use the deployer agent", or
  `APP_URL=https://… bash scripts/deploy.sh && bash scripts/smoke.sh $APP_URL` (Railway CLI logged in).
- **One-time Railway setup:** railway.com → New Project → Empty Service named `subah` → Settings →
  Networking → Generate Domain. Locally: `npm i -g @railway/cli`, `railway login`, `railway link`,
  then `bash scripts/railway_env.sh https://<domain>` (copies your `.env` settings to Railway) and
  `APP_URL=https://<domain> bash scripts/deploy.sh`. For CI: Project Settings → Tokens → create a
  project token; GitHub → Settings → Secrets → Actions: `RAILWAY_TOKEN`, `APP_URL`,
  `TEST_SUPABASE_URL`, `TEST_SUPABASE_ANON_KEY`, `TEST_SUPABASE_SERVICE_ROLE_KEY`,
  `SMOKE_EMAIL`, `SMOKE_PASSWORD`. `PUBLIC_BASE_URL` on Railway must be the public URL.
- `/health` version: `GIT_SHA` env, else `RAILWAY_GIT_COMMIT_SHA`, else the `app/VERSION` file written by
  `scripts/deploy.sh`, else `dev` (`main.version()`).

## 3. Demo data
`scripts/seed_demo.py --email demo@subah.app` creates a user (EN edition + Urdu source
language, topics ai, startups, pakistan, sports_cricket, climate; city Lahore), generates
editions for the last 3 days (real feeds), and adds signals so the profile page already
shows movement and one pending suggestion.

## 4. Manual QA before recording
- [ ] Signup → onboarding → first paper in ≤ 90 s on a phone
- [ ] Paper in `en`, `ur` (RTL Nastaliq), `hi`, `ar`, `zh` renders correct fonts on web and PDF
- [ ] PDF: masthead, columns, Three Things, clickable headlines, page footer
- [ ] Archive lists past papers; each opens and downloads
- [ ] 👍/👎 change weights (profile bars), time-travel edition reflects it
- [ ] Learner suggestion card appears and "Yes" adds the interest
- [ ] Making-of page shows the agent timeline, including a fallback if one happened
- [ ] Logged-out user cannot open any paper URL
- [ ] Favorite source story appears; muted word never appears
- [ ] 🔖 saves and shows in Saved; ✓ appears after opening a story
- [ ] Puzzle playable, score + streak shown
- [ ] Night edition + XL text persist after reload
- [ ] Push "Your paper is ready" received (Android/desktop Chrome)
- [ ] Live Railway URL passes `scripts/smoke.sh` with the SMOKE account

## 5. Loom script (≤ 5 minutes)
1. **0:00 Problem (20 s):** "News is scattered across dozens of sites. Social media has one
   feed. News doesn't. Subah is your personal morning paper."
2. **0:20 Onboarding (60 s):** sign up; pick Urdu or English; topics with "how much";
   type "Pakistani startups and F1" → Profiler turns it into chips; swipe the taste test;
   city Lahore; "Print my first paper" with the live printing steps.
3. **1:20 The paper (60 s):** the navy/maroon home: your sources row, "Your daily
   Headlines" hero with your name and edition number, Three Things, section pills, Your City.
   Open a story sheet (Listen, Save); back on home it shows ✓ read and the progress bar moves.
   Mute "celebrity" from the ⋯ menu.
4. **2:20 PDF + archive (40 s):** download the A3 broadsheet PDF; show columns and that
   links work; open the archive of earlier papers.
5. **2:50 Puzzle (15 s):** play two questions of "Fill the headline".
6. **3:05 Learning (45 s):** 👍 two EV stories, 👎 a celebrity story; open My interests →
   bars moved; time-travel to tomorrow → new order + "Add Electric vehicles?" suggestion.
7. **3:50 Languages + agents (40 s):** switch the same edition to Hindi, Arabic and
   Chinese; open "How this paper was made": Curator picks, Editor, fallbacks, timings.
8. **4:30 Night + notification (15 s):** switch to Night edition; show the "Your paper is
   ready ☕" notification.
9. **4:45 Close (15 s):** "Four agents, eight languages, one paper that learns you. Subah."

## 6. Likely judge questions
| Q | A |
|---|---|
| How is it personalised beyond topics? | Weights per interest from taste test + clicks/👍/👎/dwell; Learner discovers new interests; layout (lead, section order, style, language) changes per reader. |
| What if the AI hallucinates? | Editor only uses the feed title/summary, is told never to invent facts, every id is validated, and the original article is one tap away. Fallbacks need no AI. |
| Copyright? | We show headlines + short summaries with the source name and link to the original, like a news aggregator; no full-text copying. |
| Cost? | ≤ 3 LLM calls per edition on free tiers; PDFs cached; feeds are free RSS. |
| Why server-rendered? | One template powers both the web page and the PDF, so they always match. |
