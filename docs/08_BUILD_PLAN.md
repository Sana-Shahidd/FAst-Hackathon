# 08 — 9-Hour Build Plan (solo): Subah

Clock starts at **H0:00**. Every task ends the same way:
**Check passes → its unit + integration tests pass → ship with the `shipper` agent
(`scripts/ship.sh`) → push to `main` → GitHub Actions tests again and deploys.**
Deploy pipeline goes live in T-01 so every later feature reaches the live URL automatically.
If a task overruns by 20 min: note it in `DECISIONS.md`, keep the fallback path, move on.

| ID | Time | Task (features) | Check | Tests required (see 09 §2) |
|---|---|---|---|---|
| **T-01** | 0:00–0:25 | Public repo; add docs, `AGENTS.md`, `.claude/agents/*`, scripts, `Dockerfile`, `render.yaml`, CI, `pytest.ini`, data + i18n files. Minimal `app/main.py` with `/health`. Render: New → Blueprint from repo; add env vars; copy Deploy Hook URL; GitHub secrets. | CI green; `deployer` shows `/health` live with the commit sha | `unit/test_i18n.py`, `integration/test_health.py` |
| **T-02** | 0:25–0:50 | Two Supabase projects (prod + test), run `supabase/schema.sql` in both; Gemini + Groq keys; `config.py`, `agents/llm.py`, `runner.py`, `smoke.py`; VAPID keys (`scripts/gen_vapid.py`). | `python -m app.agents.smoke` ok for every model | `unit/test_runner_fallback.py` |
| **T-03** | 0:50–1:20 | Feeds: URL builder, parallel fetch, normalise, dedupe, **mute filter (F-18)**, **custom feed validation + catalog (F-23)**; verify `sources.json` + Google News editions. | ≥ 30 candidates for `ai,pakistan,startups` in `en` and `ur`; muting "cricket" removes cricket items | `unit/test_feeds.py`, `unit/test_mutes.py`, `unit/test_sources.py` |
| **T-04** | 1:20–1:50 | `deps.py` (cookies, `require_user`, CSRF, `t()`), auth routes, `base.html` with `data-theme`/`data-text-size`/`dir`, `app.css` tokens, bottom nav, hero gradient. | Sign up/in works; `?lang=ur` is RTL Nastaliq; navy→maroon hero renders | `integration/test_auth.py`, `integration/test_auth_scope.py` (skeleton) |
| **T-05** | 1:50–2:50 | Onboarding (F-02): language, **Choose Categories grid**, **favorite sources (F-23)**, Profiler parse, taste test, morning step with **mutes (F-18)** + **notify toggle (F-21 UI)**; `POST /onboarding`. | New user completes in < 60 s; rows in profiles, interests, favorite_sources, muted_keywords | `unit/test_profiler_fallback.py`, `integration/test_onboarding.py` |
| **T-06** | 2:50–3:45 | Edition pipeline (F-03–F-05): favorites always fetched + boost, mutes applied, Curator + Editor (+ fallbacks), **puzzle items (F-17)**, layout, freshness fields, activity log; `/paper/generate`, `/paper/status`. | Edition in ≤ 40 s with lead, sections, Three Things, 5 valid puzzle items, ≥ 1 favorite-source story | `unit/test_curator_fallback.py`, `unit/test_agent_validation.py`, `unit/test_puzzle.py`, `integration/test_generate_edition.py` |
| **T-07** | 3:45–4:45 | Home app view (F-07): sources circles, hero card, section pills, cards, ⋯ menu, article sheet, search filter; `/r/{id}`; signals; **mark as read (F-22)**; **save toggle (F-19)**. | Looks like the reference in navy/maroon on a phone; ✓ appears after opening; 🔖 fills | `unit/test_reading.py`, `integration/test_edition_page.py`, `integration/test_signals.py`, `integration/test_redirect.py` |
| **T-08** | 4:45–5:25 | Paper view + PDF (F-08): `edition_print.html`, `paper.css`, `print.css`, shared Playwright browser, upload + cache, footer. | PDF opens with correct fonts in `en`, `ur`, `hi`, `zh`; links work; Paper view = PDF | `integration/test_pdf.py` |
| **T-09** | 5:25–5:45 | Archive (F-09) + **Saved tab (F-19)** + regenerate + `/dev/time-travel`. | 3 editions in archive; saved list grouped by date | `integration/test_archive_saved.py` |
| **T-10** | 5:45–6:25 | Learning (F-10, F-11): weights incl. `save` + `puzzle_correct`, history, Learner Agent (+ fallback), suggestion card, profile bars. | 5 👍 on EV + time-travel → "Electric vehicles" suggestion; bars move | `unit/test_learning.py`, `unit/test_learner_fallback.py`, `integration/test_learning_flow.py` |
| **T-11** | 6:25–6:55 | **Headline puzzle page (F-17)**: questions, grading, score, streak. | Play 5 questions; score + streak saved; correct answers raise topic weight | `integration/test_puzzle_flow.py` |
| **T-12** | 6:55–7:20 | **Reading comfort (F-20)** (Aa sheet + settings), **morning notification (F-21)** (`sw.js`, `push.js`, subscribe, `send_ready`), scheduler (F-06) + nightly job, settings page, sources + mutes pages. | Android/desktop Chrome receives "Your paper is ready ☕"; Night + XL persist after reload | `unit/test_push.py` (pywebpush mocked), `integration/test_settings_push.py` |
| **T-13** | 7:20–7:45 | Room to explore: Your City (F-13), making-of (F-14), Three Things sheet (F-15), Listen card (F-16), language switch (F-12). | City section for Lahore; making-of timeline; switch to `es` re-renders | `integration/test_making_of.py` |
| **T-14** | 7:45–8:10 | Final hardening: rate limits, empty states, `APP_ENV=production` checks; `scripts/seed_demo.py` on prod; **deployer** full run with SMOKE account. | All smoke checks pass on the live URL; QA list (09 §4) passes | full suite green in CI |
| **T-15** | 8:10–9:00 | Architecture diagram PNG (Mermaid from 03 §2 + deploy flow from 03 §9), README screenshots, Loom ≤ 5 min (09 §5), submit form. | Submitted: repo link, Loom link, diagram | — |

## Cut lines (only if behind; keep the feature in the README roadmap)
- Behind at 5:25 → Paper view reuses the PDF template without the extra desktop side panel.
- Behind at 6:25 → Learner uses the code fallback only.
- Behind at 7:20 → drop Listen and the language switch; keep City, making-of, Three Things.
- Never cut: onboarding, web edition, PDF, archive, learning weights, favorite sources, mutes,
  save, mark as read, puzzle — they are the brief or features you chose.
