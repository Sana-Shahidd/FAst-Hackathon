# 00 — Subah Docs: Start Here

Subah is a personal morning newspaper (NaSCon'26 brief): onboarding learns your interests,
four AI agents build a fresh edition every morning from across the web, you read it on the
web or download a newspaper-style PDF, in 8 languages, and it learns from what you read.

## Use these docs with your AI coding tool
1. Repo root must contain `AGENTS.md`, `CLAUDE.md`, `docs/`, `app/i18n/`, `app/data/`.
2. First prompt:
   > Read AGENTS.md, docs/01_CONTEXT.md and docs/08_BUILD_PLAN.md. Start task T-01. Before
   > each task, read the docs it touches. Use only names from the docs. Reuse, don't rebuild.
   > Ship every task with the shipper agent (tests must pass).
3. Each next prompt: "Do T-xx with its unit + integration tests, show the Check passing,
   then use the shipper agent to ship it."

## Files
| File | Read when |
|---|---|
| `../AGENTS.md` | always, before any code |
| `01_CONTEXT.md` | always — brief mapping, languages, decisions |
| `02_PRD.md` | building any feature (F-01 … F-23) |
| `03_TECH.md` | stack, versions, architecture diagram, layout, contracts, env |
| `04_DATA.md` | any DB work (source of truth for names) |
| `05_ROUTES.md` | any page, form, HTMX fragment |
| `06_AGENTS.md` | Profiler, Curator, Editor, Learner: prompts, outputs, fallbacks |
| `07_DESIGN.md` | any template or CSS |
| `08_BUILD_PLAN.md` | what to do next (9-hour plan) |
| `09_SETUP_TEST_DEMO.md` | setup, tests, demo script, Loom |
| `DECISIONS.md` | log of choices made during the build |
| `../.claude/agents/shipper.md` | test gate: ship one tested feature per push |
| `../.claude/agents/deployer.md` | deploy frontend + backend (one service) and smoke-test it |

Ready-made content (do not regenerate): `app/i18n/*.json` (121 keys × 8 languages),
`app/data/languages.json`, `topics.json` (with icons), `sources.json`, `stopwords.json`;
plus `Dockerfile`, `render.yaml`, `.github/workflows/ci.yml`, `scripts/ship.sh`,
`scripts/deploy.sh`, `scripts/smoke.sh`, `pytest.ini`, `supabase/schema.sql`.
