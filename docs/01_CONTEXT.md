# 01 — Context: Subah

## 1. One line

Subah is a personal morning newspaper: AI agents learn what a reader cares about, gather
those stories from across the web every morning, and publish one edition — on the web and
as a newspaper-style PDF — in the reader's language, getting better every day.

## 2. The problem (from the NaSCon'26 brief)

News is scattered across dozens of sites, apps and newsletters. Social media has one
feed; news has nothing like it. People jump from link to link and still can't name three
things they learned.

## 3. What the brief requires → where we cover it

| Brief requirement | Feature IDs (`02_PRD.md`) |
|---|---|
| 1. Onboarding that captures interests with a great experience | F-01, F-02 |
| 2. Daily PDF, fresh every day, inspired by a traditional newspaper, personalised in content AND presentation | F-05, F-06, F-08 |
| 3. Webpage: complete reading experience, same edition downloadable as PDF, previous papers accessible | F-07, F-08, F-09 |
| 4. Learning: better at understanding interests over time | F-10, F-11 |
| 5. Room to explore | F-12 (8 languages), F-13 (Your City), F-14 (How this paper was made), F-15 (Three Things), F-16 (Listen), F-17 (Headline puzzle), F-21 (Morning notification) |
| Reader control (attachment list) | F-18 (Mute keywords), F-19 (Save for later), F-20 (Reading comfort), F-22 (Mark as read), F-23 (Favorite sources) |
| Rules: public GitHub repo, commits monitored | `AGENTS.md` Rule 5 |
| Submit: repo link, ≤ 5-min Loom, architecture diagram | `08_BUILD_PLAN.md` T-14, `03_TECH.md` §2 |

## 4. Users

| Persona | Need |
|---|---|
| Busy professional (EN) | 10 minutes of the right stories over breakfast, nothing else |
| Urdu/Hindi/Arabic reader | A real newspaper in their own script, not English-only feeds |
| Student / niche hobbyist | Depth on 2–3 narrow topics (e.g. "Pakistani startups", "F1") |
| Judge | Sees onboarding → a beautiful paper → it changes after clicks, in < 5 minutes |

## 5. Languages (8)

| Code | Language | Script / dir | Display font (Google Fonts) | Google News edition (`hl`, `gl`, `ceid`) |
|---|---|---|---|---|
| `en` | English | Latin, LTR | DM Serif Display + Inter (paper body: Source Serif 4) | `en-US`, `US`, `US:en` |
| `ur` | Urdu | Nastaliq, **RTL** | Noto Nastaliq Urdu | `ur`, `PK`, `PK:ur` |
| `ar` | Arabic | Naskh, **RTL** | Noto Naskh Arabic | `ar`, `EG`, `EG:ar` |
| `hi` | Hindi | Devanagari, LTR | Noto Serif Devanagari | `hi`, `IN`, `IN:hi` |
| `bn` | Bengali | Bengali, LTR | Noto Serif Bengali | `bn`, `BD`, `BD:bn` |
| `es` | Spanish | Latin, LTR | DM Serif Display + Inter (paper body: Source Serif 4) | `es-419`, `MX`, `MX:es-419` |
| `fr` | French | Latin, LTR | DM Serif Display + Inter (paper body: Source Serif 4) | `fr`, `FR`, `FR:fr` |
| `zh` | Chinese (Simplified) | Han, LTR | Noto Serif SC | `zh-CN`, `CN`, `CN:zh-Hans` |

Reader chooses **edition language** (headlines + summaries are written in it) and may tick
**extra source languages** (stories in those languages are also fetched, then summarised in
the edition language). The original article always opens in its own language.

## 6. Fixed decisions

| Area | Decision |
|---|---|
| Name | Subah (masthead "Subah"; rename in `config.py` `PAPER_NAME`) |
| Team / time | Solo, 9 hours |
| Budget | $0, free tiers |
| App | FastAPI + Jinja2 server-rendered pages + HTMX; no SPA. App UI in the reference mobile style, navy blue + maroon; Paper view + PDF as a classic broadsheet |
| Data/Auth/Storage | Supabase |
| Agents | `openai-agents` SDK; models via Gemini (primary) and Groq (fallback) OpenAI-compatible endpoints |
| News | RSS via `feedparser`: Google News RSS search per interest + a curated feed list |
| PDF | Same Jinja edition template, print CSS, Playwright Chromium `page.pdf()` |
| Hosting | One Docker image (frontend pages + backend API + Playwright) on Render, deployed by GitHub Actions after tests pass; local + Cloudflare tunnel as backup |
| Workflow | One feature per push, only after unit + integration tests pass (`shipper` agent); deploys via the `deployer` agent (`.claude/agents/`) |

## 7. Out of scope (say "roadmap" if asked)

Paid-wall content, full-text extraction of every article, native apps, email delivery,
social sharing, ads.

## 8. Glossary

| Term | Meaning |
|---|---|
| Edition | One user's paper for one date (`editions`). Edition number = count of that user's editions. |
| Candidate | A fetched feed item before ranking (`articles`). |
| Edition article | A candidate placed in an edition with a section, slot, headline, summary (`edition_articles`). |
| Interest | A weighted topic in the user's profile (`interests`), e.g. "AI startups" 0.8. |
| Signal | A reader action: open, click, skip, more_like, less_like, dwell, pdf (`signals`). |
| Slot | Layout position: `lead`, `secondary`, `brief`. |
