# 07 — Design: Subah

Two looks, one product:

1. **The app** (onboarding, home/edition, article sheet, saved, archive, profile, puzzle,
   settings) follows the reference mobile design — deep gradient backgrounds, white rounded
   cards, pill chips, round icon buttons, a floating bottom nav — recoloured in **navy blue
   and maroon**.
2. **The paper** (Paper view + PDF) is a classic broadsheet newspaper, because the brief asks
   for a PDF inspired by a traditional newspaper. It uses the same palette sparingly so both
   feel like one brand. Paper view and PDF are the same HTML, so the web edition always
   matches the PDF.

No component library: hand-written CSS in `static/app.css` (app) and `static/paper.css` +
`static/print.css` (paper). Icons: Lucide via `https://unpkg.com/lucide@0.460.0/dist/umd/lucide.min.js`
(`<i data-lucide="bookmark"></i>` + `lucide.createIcons()`).

## 1. Tokens (`static/app.css`)

```css
:root {
  /* brand */
  --navy-950: #07142B;  --navy-800: #0F2547;  --navy-600: #1E3A6B;  --navy-200: #C9D4E8;
  --maroon-800: #5A1426; --maroon-600: #7F1D33; --maroon-400: #B04A5E; --blush: #F6E7EB;
  /* surfaces */
  --canvas: #EEF1F6;      /* behind the phone column on desktop */
  --card: #FFFFFF;
  --ink: #0E1626;  --muted: #5E6678;  --line: #E3E7EF;
  --glass: rgba(255,255,255,.14);  --glass-line: rgba(255,255,255,.28);
  --hero: linear-gradient(165deg, #07142B 0%, #13294F 38%, #5A1426 78%, #7F1D33 100%);
  --success: #1F8A5B;  --danger: #B3263E;
  /* type */
  --font-display: var(--lang-display, "DM Serif Display"), Georgia, serif;
  --font-ui: var(--lang-ui, "Inter"), system-ui, sans-serif;
  /* shape */
  --r-card: 22px; --r-hero: 28px; --r-pill: 999px;
  --shadow: 0 8px 24px rgba(7,20,43,.12);
}
html[data-theme="night"] {
  --canvas: #050D1D; --card: #0F2547; --ink: #EEF1F6; --muted: #A8B3C9; --line: #1E3A6B;
  --blush: #2A1520; --shadow: 0 8px 24px rgba(0,0,0,.4);
}
@media (prefers-color-scheme: dark) {
  html[data-theme="auto"] { --canvas: #050D1D; --card: #0F2547; --ink: #EEF1F6; --muted: #A8B3C9; --line: #1E3A6B; --blush: #2A1520; }
}
html[data-text-size="S"]  { font-size: 15px; }
html[data-text-size="M"]  { font-size: 17px; }
html[data-text-size="L"]  { font-size: 19px; }
html[data-text-size="XL"] { font-size: 21px; }
body { background: var(--canvas); color: var(--ink); font-family: var(--font-ui); }
```
Fonts (Google Fonts): `DM Serif Display` (headings) + `Inter` (UI) for Latin languages;
per-language overrides from `languages.json` set `--lang-display` / `--lang-ui`
(Noto Nastaliq Urdu, Noto Naskh Arabic, Noto Sans/Serif Devanagari, Noto Sans/Serif Bengali,
Noto Serif SC / Noto Sans SC). Urdu line-height 2.1, Arabic 1.8, others 1.5.
`<html lang dir data-theme data-text-size>` set server-side from the profile. Use logical
CSS properties everywhere so RTL mirrors automatically (the bottom nav and chip rows flip).

Contrast: white text on `--hero` passes AA everywhere (darkest stop navy, lightest maroon
#7F1D33 vs white = 9.3:1). Maroon `--maroon-600` on white = 9.6:1 — safe for small labels.

## 2. Layout frame
- Mobile: full width. Desktop ≥ 900 px: a centered 480 px "phone column" on `--canvas`,
  with the "Paper view" preview and the archive mini-pages in a side panel on the right
  (≥ 1200 px). The app never stretches cards to desktop width.
- Floating bottom nav (all signed-in app pages): white pill, 16 px from bottom
  (+ `env(safe-area-inset-bottom)`), shadow; 4 items with Lucide icons: **Home** (`house`),
  **Archive** (`compass`), **Saved** (`bookmark`), **Profile** (`user-round`). Active item =
  navy-950 pill with icon + label in white (like the reference "Home"); others icon-only
  round 44 px buttons.

## 3. Screens

### 3.1 Home / today's edition (`edition.html`) — reference screen 2
```
[hero gradient background, top ~55% of first screen]
 (S)  avatar initial circle           (🔍) (🔔) (Aa)   ← white round buttons 44 px
 Your sources: (BBC) (Dawn) (AJ) (TC) (+)               ← 56 px circles, initials on brand color,
                                                           white ring; tap filters; (+) → /sources
 ┌ hero card (white glass, r=28) ─────────────────────┐
 │ Your daily                         [Three things]  │ ← maroon pill badge (opens sheet)
 │ Headlines   (DM Serif 40px)                        │
 │ Sana's edition · No. 12 · Sat, 17 Oct              │
 │ [lead image r=22]  Lead headline (serif 22)        │
 │                    dek (2 lines)                   │
 │ Printed 06:02 from 23 sources · 6 of 14 read ━━━─  │ ← progress bar maroon
 └────────────────────────────────────────────────────┘
[canvas below]
 (All) (Technology) (Pakistan) (Cricket) …  ← pills; active = navy-950 filled, others maroon-tint glass
 Technology                            See all
 ┌ card r=22 ───────────────────────────────┐
 │ [image 16:9]  (3 hours ago) chip   (⋯)   │ ← chip = dark glass on image
 │ BBC · ✓ read                             │
 │ Headline (serif 19)                      │
 │ summary (2-3 lines)                      │
 │ Why you're seeing this ▸                 │
 └──────────────────────────────────────────┘
 ┌ Today's puzzle · Fill the headline · 5 questions  [Play] ┐ ← maroon gradient card
 Editor's note card · Learner suggestion card ("Add 'Electric vehicles'?" Yes / No thanks)
 [Paper view] [Download PDF]   ← two pill buttons (navy filled / outline)
 [bottom nav]
```
- Cards without images: no empty image box; headline gets a maroon section label above.
- Read cards: headline weight 500 + muted colour, small `check` icon.
- "⋯" opens an action sheet: More like this · Less like this · Save · Mute a word · Hide source.
- Search (🔍): slide-down input filtering visible cards client-side by headline/summary text.
- Bell (🔔): notification toggle sheet (F-21). Aa: text size S–XL + Day/Night/Auto (F-20).

### 3.2 Article sheet — reference screen 3
Full-height bottom sheet over the hero gradient: large image (r=28) → **Listen card**
(glass card with a static decorative waveform made of 40 thin bars via CSS, play button,
elapsed/total time from `speechSynthesis` progress estimate) → row: time chip "3 hours ago",
source, then round Save (`bookmark`) and Share (`share-2`, copies the `/r/` link) buttons →
headline (serif 26, white) → summary (white 85%) → "Why you're seeing this" → big pill
button "Read the original at BBC →" (white, navy text).

### 3.3 Onboarding — reference screen 1 ("Choose Categories")
Hero gradient full screen; back button = white circle with `chevron-left`; title area
"Subah" small, then serif "Choose Categories" + subtitle in white.
- Step 1 Language: 2-column white cards, each language in its own script + English name.
- Step 2 Topics: 2-column grid of white cards exactly like the reference: top line =
  small check-circle icon + badge text (e.g. "Tech Trends") in muted 11 px; round 40 px icon
  bubble (Lucide icon per topic, `--blush` bg, maroon icon); title (semibold 15);
  one-line description (muted 12). Selected = `--blush` card background + 2 px maroon border +
  "how much" segmented control (a little / a lot / obsessed) under the description.
  Below: "Your favorite sources" — circles row like the home screen + "Paste any RSS link".
- Step 3 free text, step 4 taste-test cards (white card stack, swipe), step 5 morning
  settings + mute chips + notification toggle.
- Primary button: full-width navy-950 pill "Continue" (last step "Print my first paper").
- Progress: 5 small dots at top; active dot = white wide pill.
- Printing screen: hero gradient, masthead letters drop in one by one, live step list from
  `/paper/status` in white glass rows.

### 3.4 Saved, Archive, Profile, Puzzle, Settings
- **Saved:** title "Saved for later", grouped by date headers, compact cards (thumbnail left
  72 px r=16, headline, source · date, filled bookmark to unsave).
- **Archive:** grid of mini front pages (white cards r=22 showing masthead "Subah", No.,
  date, lead headline in serif) — 2 per row mobile.
- **Profile:** hero header with name + streak; "Your interests" — bars (navy track, maroon
  fill) with weight and a tiny sparkline (inline SVG polyline); "What I learned about you"
  note cards; links to Sources, Mutes, Settings.
- **Puzzle:** hero gradient; a "newspaper clipping" white card with the masked headline in
  serif and `___` underlined in maroon; 4 choice pills (2×2); correct = green pill + check,
  wrong = maroon outline + shake (disabled for reduced motion); after 5: score ring, streak,
  "Read these stories" list.
- **Settings:** grouped white cards (Edition, Reading comfort, Notifications, Sources, Never
  show me, Account); each row 56 px with a chevron.

## 4. Topic card content (step 2)
`app/data/topics.json` gets `icon` (Lucide name) and `badge` per topic; badge labels are i18n
keys `badge.<topic>` (fallback: show only the title). Icons: world `globe`, pakistan `flag`,
south_asia `map`, middle_east `landmark`, us_politics `vote`, business `briefcase`,
markets `trending-up`, startups `rocket`, technology `cpu`, ai `sparkles`, science
`flask-conical`, space `orbit`, health `heart-pulse`, climate `leaf`, sports_cricket
`trophy`, sports_football `volleyball`, f1 `flag-triangle-right`, entertainment
`clapperboard`, film_tv `tv`, music `music`, books `book-open`, gaming `gamepad-2`,
food `utensils`, travel `plane`.

## 5. The paper (Paper view `/paper/{date}/print` + PDF)
- White newsprint background (#FFFFFF with a faint #FBFAF8 tint), ink #0E1626.
- Masthead "Subah" in DM Serif Display 96 px navy-950, thin maroon double rule under it;
  dateline row: "Sana's edition · No. 12 · localized date · Printed 06:02 from 23 sources".
- Front page: lead across 3 of 5 columns with image; "Three things to know today" box with
  maroon top border; secondaries; then sections with maroon small-caps labels and column
  rules (`columns: 5; column-rule: 1px solid #DADFE8` on A3).
- Favorite sources credited on page 1: "From your sources: BBC · Dawn · Al Jazeera".
- Text size from profile applied to body text. Day colours only.
- Footer via Playwright `footer_template`: "Subah · {date} · page X/Y".
- Last page: "How this paper was made" mini summary + `t('puzzle.pdf_line')`.
- Every headline is a link to `{PUBLIC_BASE_URL}/r/{id}`.

## 6. UI text
All strings in `app/i18n/{lang}.json` — 121 keys, identical in all 8 files (UI, topics,
new-feature strings). Placeholders use `{name}` → `t(key, **vars)` via `str.format`.
New keys must be added to all 8 files (fallback `en`). Have a native speaker glance at any
non-English language you demo.

## 7. Motion & accessibility
- Motion: cards fade-up 150 ms on load; sheet slides up 200 ms; masthead print animation;
  all disabled with `prefers-reduced-motion`.
- Touch targets ≥ 44 px; visible focus ring 2 px maroon-400; icon buttons have translated
  `aria-label`; images `alt` = headline; colour never the only state signal (read = ✓ icon,
  saved = filled icon, selected card = border + check).
