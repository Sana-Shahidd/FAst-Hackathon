# 02 — Product Requirements: Subah

Feature IDs are referenced by the build plan and tests. "MUST" = required.

## Success in the demo

| Metric | Target |
|---|---|
| Signup → first edition on screen | ≤ 90 s (onboarding ~45 s + generation ≤ 40 s) |
| Edition generation (fetch + 2 agent calls + render) | ≤ 40 s |
| PDF download after edition exists | ≤ 8 s (cached after first render) |
| Visible change in tomorrow's paper after 5 clicks / 3 skips | interest weights move; regenerated edition reorders sections |

---

## F-01 Signup / login
- Supabase email + password (`/signup`, `/login`, `/logout`). Confirm-email OFF for demo.
- After first login with no profile → redirect to `/onboarding`.

## F-02 Onboarding (target: under 60 seconds, fun)
Five steps on one page (`/onboarding`), HTMX swaps each step, progress bar on top,
"Back" on every step. Saved with `POST /onboarding` at the end (one transaction).

1. **Language** — big tiles for 8 languages in their own script ("English", "اردو",
   "العربية", "हिन्दी", "বাংলা", "Español", "Français", "中文"). Choosing one immediately
   switches the onboarding UI language and direction. Optional "Also read news in…" chips
   (extra source languages).
2. **Topics + sources** — "Choose Categories" grid of 24 topic cards (list below; card =
   small badge line, icon, title, one-line description, as in `07_DESIGN.md` §4), multi-select,
   min 3. Each selected card shows a 3-level "how much" toggle (a little / a lot / obsessed →
   weight 0.4 / 0.7 / 1.0). Below the grid: **"Your favorite sources"** (F-23) — outlet logo
   chips for the edition language from `app/data/sources.json` (e.g. Dawn, BBC, Al Jazeera),
   multi-select, plus "Paste any RSS link" field.
3. **Your own interests** — free text "Anything specific? e.g. Pakistani startups, F1,
   climate in South Asia" (≤ 200 chars). The **Profiler Agent** turns it into 1–5 extra
   interests (shown as chips the user can remove) — HTMX call `POST /onboarding/parse`.
4. **Taste test** — 8 real headlines fetched live for the chosen topics (from the topic feeds,
   in the edition language when available). User taps 👍 / 👎 / skip on each (cards, swipe on
   mobile). 👍 = +0.15 to that article's topic, 👎 = −0.15. This is the "great experience"
   moment: they see real news before the paper exists.
5. **Your morning** — city (text, optional; enables F-13), timezone (auto from browser
   `Intl.DateTimeFormat().resolvedOptions().timeZone`, editable), reading time
   (5 / 10 / 20 min → 8 / 14 / 22 articles), "Never show me" muted keywords (F-18, chips,
   optional), and "Tell me when my paper is ready" toggle (F-21, asks browser notification
   permission). Button: **"Print my first paper"** → generates edition → `/paper/today`.

Topic list (key → label EN; labels for all languages in `07_DESIGN.md` §6):
`world, pakistan, south_asia, middle_east, us_politics, business, markets, startups,
technology, ai, science, space, health, climate, sports_cricket, sports_football, f1,
entertainment, film_tv, music, books, gaming, food, travel`.

## F-03 Sources
- **Topic feeds:** each topic key maps to a Google News RSS search query in
  `app/data/topics.json` (e.g. `ai` → `"artificial intelligence" OR "AI model"`), built
  per language with the edition's `hl/gl/ceid` (`01_CONTEXT.md` §5):
  `https://news.google.com/rss/search?q={urlencoded}&hl={hl}&gl={gl}&ceid={ceid}`.
- **Custom interests:** same search URL with the interest text as the query.
- **Curated feeds:** `app/data/feeds.json` — 2–4 reliable RSS feeds per language
  (verified during T-03; any feed returning 0 items is removed and noted in DECISIONS.md).
- **City:** search query `"{city}"` in the edition language (F-13).
- **Favorite sources (F-23):** each chosen outlet's RSS feed is always fetched; pasted RSS
  links are fetched the same way (max 5 custom feeds per user).
- If a language edition returns < 5 items for a query, also fetch the English query and let
  the Editor summarise in the edition language.

## F-04 Fetch + clean (code, no AI)
- Fetch all feed URLs concurrently with httpx (timeout 6 s each, max 25 URLs per edition),
  parse with `feedparser.parse(response.text)`.
- Keep items published in the last 36 h (fallback 72 h if fewer than 30 candidates).
- Normalise: title, link, source name (`entry.source.title` or feed title), published,
  summary text (HTML stripped, ≤ 600 chars), image URL (`media_content`/`media_thumbnail`
  /`enclosures` if present), `topic_key` or `interest_id` that fetched it, language.
- Dedupe: exact URL, then `rapidfuzz.fuzz.token_set_ratio(title_a, title_b) ≥ 85` → keep
  the one with an image / longer summary.
- Exclude articles the user already received in the last 3 editions (same URL or fuzzy title).
- **Mute filter (F-18):** drop any candidate whose title or summary contains a muted keyword
  (case-insensitive, whole-word match with `re` word boundaries; for scripts without spaces —
  `zh` — plain substring). Done in code before the Curator; counted in the making-of log.
- Store in `articles` (upsert by `url_hash`).

## F-05 Edition generation (agents)
`services/edition.py::generate_edition(user_id, date)`:
1. Load profile + interests (weights) + recent signals.
2. Fetch candidates (F-04), max 120.
3. **Curator Agent** ranks and picks N (from reading time) with a section for each
   (`06_AGENTS.md` §3). Fallback: score = interest weight × recency × (1.2 if image).
4. **Editor Agent** writes, in the edition language: front-page lead headline + 2-sentence
   dek, a short headline + 1–3 sentence summary for every picked article, section order,
   a "Why you're seeing this" reason per article, the **Three Things** (F-15) and the
   **Editor's Note** (1–2 sentences addressing the reader). Fallback: original titles,
   feed summaries, sections ordered by interest weight.
5. Assign slots: 1 `lead` (front page), 2–4 `secondary`, rest `brief`.
6. Save `editions` + `edition_articles`; edition number increments per user.
7. Log every step to `agent_activity`.
- One edition per user per date; "Regenerate" (demo button) replaces today's edition
  (`editions.version++`) and keeps the old one in the archive as `superseded`.

## F-06 Daily schedule
APScheduler job every 15 minutes: for users whose local time just passed `delivery_time`
(default 06:00) and have no edition for their local date → `generate_edition`. Also the
"Get today's paper" button generates on demand.

## F-07 Web edition (`/paper/{date}` and `/paper/today`) — app view
App-style reading screen from `07_DESIGN.md` §3 (navy→maroon gradient, white cards, pill
chips, floating bottom nav), same content and order as the PDF:
- Header: avatar initial (→ profile), search (filters today's cards client-side), bell
  (notification settings, F-21).
- "Your sources" circles row: favorite sources (F-23); tapping one filters cards to it.
- Hero card "Your daily Headlines": masthead line ("Sana's edition · No. 12 · localized
  date · Printed 06:02 from 23 sources"), lead story image + headline + dek, badge
  "Three things" opening the Three Things sheet (F-15), editor's note.
- Section pills (All + personalised section order); section blocks with "See all".
- Article card: image (if any), "3 hours ago" chip, source, headline, summary, ✓ read tick
  (F-22), "Why you're seeing this" (tap), and a "⋯" menu: 👍 More like this · 👎 Less like this
  · 🔖 Save (F-19) · 🔇 Mute a word (F-18) · ✕ Hide this source. Headline/image open the
  article via `/r/{id}` (new tab). Actions are HTMX POSTs; card updates in place.
- Article detail sheet (`/paper/{date}/a/{edition_article_id}`, HTMX bottom sheet): large
  image, Listen card (F-16, waveform style), time chip, Save + Share (copy link) buttons,
  headline, full summary, "Read the original at {source} →".
- "Today's puzzle" card after the front page (F-17).
- **Paper view** button: opens the classic newspaper layout (`/paper/{date}/print`) — the
  exact HTML the PDF is printed from — so the web edition and PDF always match.
- Top-right overflow: Download PDF, Read in another language, How this paper was made.

## F-08 PDF edition
- `GET /paper/{date}/pdf` → if `editions.pdf_path` exists, stream it from Supabase Storage;
  else render `edition_print.html` (same data, print CSS) with Playwright
  `page.set_content(html, wait_until="networkidle")` → `page.pdf(format="A3",
  print_background=True, margin={"top":"12mm","bottom":"14mm","left":"12mm","right":"12mm"})`,
  upload to bucket `papers` at `{user_id}/{date}-v{version}.pdf`, save path, stream.
- Classic broadsheet only (5 columns on A3) — one style done well. The PDF uses the
  navy/maroon palette sparingly (masthead rule, section labels) on white newsprint.
- Personalised presentation: section order and front-page lead chosen per reader, pinned
  favorite sources credited on the front page, edition language + script fonts, reader's
  name in masthead, text size (F-20) applied to body text.
- Every headline in the PDF is a clickable link to `/r/{id}` (absolute `PUBLIC_BASE_URL`).
- One Playwright browser instance is started on app startup and reused.

## F-09 Archive (`/archive`)
Calendar-style list of previous editions (date, edition no., lead headline, language),
newest first, each with "Read" and "PDF". Superseded versions shown collapsed.

## F-10 Learning signals
| Signal | Recorded when | Weight change to article's topic/interest |
|---|---|---|
| `click` | `/r/{id}` opened | +0.08 |
| `more_like` | 👍 | +0.15 |
| `less_like` | 👎 | −0.15 |
| `skip_source` | ✕ | source added to `blocked_sources` |
| `dwell` | page visible ≥ 20 s after returning from a click (`visibilitychange` + `navigator.sendBeacon('/signals')`) | +0.04 |
| `impression_no_click` | edition 2+ days old with no click on that article | −0.02 (applied by nightly job) |
| `pdf` | PDF downloaded | none (stats only) |
| `save` | 🔖 saved | +0.10 |
| `puzzle_correct` | headline puzzle answered right | +0.03 to that article's topic |
Weights clamp to [0.05, 1.0]; interests below 0.1 for 7 days become inactive. All changes
are written to `interest_history` so the reader can see their profile evolve.

## F-11 Learner Agent ("What I learned about you")
- After ≥ 5 signals since last run (and nightly), the **Learner Agent** reads recent
  clicked/liked/disliked headlines + current interests and returns: up to 3 **new interest
  suggestions** (e.g. clicked 4 EV stories → "Electric vehicles"), up to 2 interests to
  lower, and a one-sentence note in the edition language.
- Suggestions appear on the next edition as a card "Add 'Electric vehicles' to your paper?"
  (Yes / No). Yes → interest at weight 0.5, source `learned`.
- `/profile` page: current interests as bars (weight), history sparkline per interest,
  learned suggestions, the note. Reader can edit or delete anything.

## F-12 Eight languages (Room to explore)
Edition language from onboarding/settings; UI fully translated (string table); RTL for
`ur`/`ar`; script-specific fonts in web + PDF; localized dates via babel
(`format_date(date, format="full", locale=lang)`); "Read in another language" switch.

## F-13 Your City (Room to explore)
If a city is set: a "Your City" section with up to 3 local stories (Google News query for the
city in the edition language) shown on page 2. Hidden if no stories.

## F-14 How this paper was made (Room to explore)
`/paper/{date}/making-of`: timeline of `agent_activity` for that edition — sources fetched
(counts), candidates found, duplicates removed, Curator picks with reasons, Editor output,
fallbacks used. Linked from the PDF footer and web masthead. Great for judges.

## F-15 Three Things (Room to explore)
Front-page box: "Three things to know today" — the Editor's 3 one-line takeaways from the
edition. Directly answers the brief's "can't name three things they learned".

## F-16 Listen (Room to explore, last if time allows)
"Listen to the front page" button using the browser `speechSynthesis` API with
`utterance.lang` = edition language (no server cost). Hidden if the browser has no voice
for that language.

## F-17 Headline puzzle
- Each edition has a 5-question "Fill the headline" game: a headline from today's paper
  with one key word hidden ("Pakistan ___ India by six wickets"), 4 choices.
- Items come from the Editor Agent (`puzzle` field, `06_AGENTS.md` §6) in the edition
  language; fallback built in code (longest non-stopword in the headline; 3 decoys = same-length
  words from other headlines). Stored in `puzzles`.
- `/puzzle/{date}`: one question at a time, newspaper-clipping card, tap a choice → right/wrong
  reveal with the full headline linking to the article; score "4/5" + streak (consecutive days
  with a completed puzzle). Results in `puzzle_attempts`.
- Card on the web edition ("Today's puzzle · 5 questions"); not in the PDF (shows a small
  "Play today's puzzle at subah… " line instead).

## F-18 Mute keywords
- "Never show me" list (≤ 30 words/phrases, ≤ 40 chars each) set in onboarding step 5,
  Settings, or from an article's ⋯ menu ("Mute a word" → choose a word from the headline or type one).
- Applied in code before ranking (F-04); never sent to the LLM. Settings shows how many
  stories each mute removed in the last 7 days (from `agent_activity` data).

## F-19 Save for later
- 🔖 on any article card or detail sheet → `saved_articles` (toggle). Bookmark icon filled
  when saved.
- Bottom-nav "Saved" tab (`/saved`): saved articles grouped by edition date, newest first,
  with unsave. Saved articles survive archive regeneration (rows reference `articles`).

## F-20 Reading comfort
- Text size: S / M / L / XL (`profiles.text_size` → root font-size 15 / 17 / 19 / 21 px).
- Theme: Day / Night / Auto (`profiles.theme`; Night = deep navy background, cream text).
- Controls in Settings and in the "Aa" button of the edition header; saved per user (server)
  and applied via `<html data-theme data-text-size>`. PDF uses text size, always Day theme.

## F-21 Morning notification
- Web Push with VAPID via `pywebpush`. Opt-in in onboarding step 5 or Settings ("Tell me
  when my paper is ready"); the browser asks permission; subscription saved via
  `POST /push/subscribe`.
- Service worker `/sw.js` (served from root so its scope covers the app) shows the
  notification and opens `/paper/today` on click.
- Sent by the scheduler right after a scheduled edition is ready: title "Your paper is ready
  ☕", body = lead headline (edition language). Expired subscriptions (HTTP 404/410) deleted.
- Note for the demo: iOS Safari supports web push only for sites added to the Home Screen;
  demo on Android Chrome or desktop Chrome.

## F-22 Mark as read
- An article counts as read when opened via `/r/{id}` or its detail sheet (signal `open`
  or `click`). Cards show a small ✓ and reduced headline weight; the hero shows progress
  "6 of 14 read" with a thin progress bar.
- Read state is derived from `signals` (no extra table); one query per page
  (`read_ids_for_edition`).

## F-23 Favorite sources
- Catalog `app/data/sources.json`: outlets per language (1–8; English outlets are also offered
  to every other language, listed after the native ones) with name, domain, RSS URL, logo
  initials + brand color (no logo images needed).
- Onboarding step 2 + Settings: pick outlets; paste up to 5 custom RSS/Atom URLs (validated by
  fetching once with `feedparser`; reject if `bozo` and 0 entries, or not http(s)).
- Effect: favorite feeds always fetched (F-03); Curator gets `favorite_sources` and code adds
  a ranking boost ×1.25 in fallback scoring; at least 1 story from favorites per edition if
  any are fresh. Shown as the "Your sources" circles row (F-07).
- Removing a favorite stops fetching it from the next edition.

## F-24 Ask Subah (question answering)
- A question box on the web edition: the reader types a question ("what happened with the central
  bank today?"), the app searches **today's paper** (headlines + summaries) and a **live Google News
  search** for the question in the edition language, ranks the matches in code, and the **Answerer
  Agent** writes a short answer (2-4 sentences, edition language) from ONLY those stories.
- The answer cites the stories it used (title, source, link); stories from the paper link through
  `/r/{id}`. If the Answerer fails or the stories do not answer the question, the box shows the
  closest stories without an answer text (code fallback). Question ≤ 200 characters; rate limit
  10 per minute per reader. Only the question and article data are sent to the model.

## Non-functional
- Mobile-first app view (single column < 720 px; centered 480 px phone-width column with
  side panels on desktop); Paper view and PDF use newspaper columns.
- Page loads < 1.5 s once an edition exists (server-rendered, no SPA).
- No LLM failure blocks an edition (fallbacks).
- Max 3 LLM calls per edition (Curator, Editor, optional Learner) → fits free tiers.
