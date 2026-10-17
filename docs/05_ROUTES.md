# 05 — Routes: Subah

Server-rendered app. "Page" = full HTML (extends `base.html`). "Fragment" = HTMX partial
(no layout). Auth: `none` or `user` (`deps.require_user` → redirects to `/login` for pages,
`401` for fragments/JSON). All POST forms include a CSRF token (`deps.csrf_token()` in a
hidden input + `HX-Request` header check; token = HMAC of session id with `SECRET_KEY`).

| Method | Path | Auth | Returns | Notes |
|---|---|---|---|---|
| GET | `/` | none | page `landing.html` | logged in → redirect `/paper/today` (or `/onboarding` if not onboarded) |
| GET/POST | `/signup` | none | page / redirect | Supabase `auth.sign_up`; create `profiles` row; rate 5/min/IP |
| GET/POST | `/login` | none | page / redirect | Supabase `auth.sign_in_with_password`; set cookies `sb_access`, `sb_refresh`; rate 10/min/IP |
| POST | `/logout` | user | redirect `/` | clear cookies, `auth.sign_out` |
| GET | `/onboarding` | user | page with step 1 | |
| GET | `/onboarding/step/{n}` | user | fragment `_ob_step{n}.html` | `n` 1–5; `?lang=` re-renders UI language live |
| POST | `/onboarding/feed` | user | fragment: feed chip or error | form `url`; validates one pasted RSS/Atom link (public host, parses as a feed); returns a removable chip or `sources.invalid` |
| POST | `/onboarding/parse` | user | fragment: interest chips | form `text` ≤ 200 → Profiler Agent; fallback: split by commas |
| GET | `/onboarding/taste` | user | fragment: 8 `_taste_card.html` | `?topics=ai,startups&lang=ur`; quick fetch of 1 feed per topic (timeout 5 s) |
| POST | `/onboarding` | user | redirect `/paper/generate?first=1` | whole onboarding form (§ below); upserts profile + interests + taste signals |
| GET | `/paper/generate` | user | page "Printing your paper…" | starts `generate_edition` in background, page polls `/paper/status` |
| POST | `/paper/generate` | user | redirect | `regenerate=1` → new version; rate 3/10 min/user |
| GET | `/paper/status` | user | fragment | `ready` → `HX-Redirect: /paper/today`; shows live steps from `agent_activity` |
| GET | `/paper/today` | user | page `edition.html` | user's local date; no edition yet → `/paper/generate` |
| GET | `/paper/{date}` | user | page `edition.html` | `date` = `YYYY-MM-DD`; latest non-superseded version; `?lang=` shows a translation (Editor Agent, cached in `edition_translations`); `?v=` a specific version |
| GET | `/paper/{date}/pdf` | user | `application/pdf` | `Content-Disposition: attachment; filename="Subah-{date}.pdf"`; records `pdf` signal |
| GET | `/paper/{date}/making-of` | user | page `making_of.html` | agent_activity timeline |
| GET | `/archive` | user | page `archive.html` | all editions, newest first |
| GET | `/r/{edition_article_id}` | user | `302` to stored article URL | records `click`; 404 if not the user's edition |
| POST | `/signals` | user | fragment (empty / toast) or `204` | form or beacon: `edition_article_id`, `kind` ∈ `more_like, less_like, skip_source, dwell`, `value` |
| GET | `/profile` | user | page `profile.html` | interests with weights + history, suggestions, learner notes |
| POST | `/interests` | user | fragment | add / update weight / delete (`action` field) |
| POST | `/suggestions/{id}` | user | fragment | `decision` = `accept`/`reject` |
| GET/POST | `/settings` | user | page / redirect | edition_lang, source_langs, city, timezone, reading_minutes, text_size, theme, notify, delivery_time, display_name; links to `/sources` and mutes |
| GET | `/paper/{date}/a/{edition_article_id}` | user | fragment: article detail sheet | records `open` signal (mark as read, F-22) |
| GET | `/paper/{date}/print` | user | page `edition_print.html` | "Paper view": exact HTML used for the PDF |
| GET | `/puzzle/{date}` | user | page `puzzle.html` | F-17; `today` allowed |
| POST | `/puzzle/{date}/answer` | user | fragment: result card | `q` (0–4), `choice`; idempotent per question; updates `puzzle_attempts`; correct → `puzzle_correct` signal |
| POST | `/saved/{edition_article_id}` | user | fragment: bookmark button | toggles save (F-19); records `save` signal on save |
| GET | `/saved` | user | page `saved.html` | saved articles grouped by edition date; `POST /saved/{id}` with `ctx=saved` unsaves and returns the refreshed list |
| POST | `/ask` | user | fragment `_ask_answer.html` | F-24; form `q` (≤ 200 chars); answer + cited stories; 10/min/user |
| POST | `/mutes` | user | fragment: mute chips | `action` = `add`/`remove`, `keyword` (2–40 chars, lower-cased, trimmed); max 30 |
| GET | `/sources` | user | page `sources.html` | catalog for edition language + English, current favorites, custom feeds |
| POST | `/sources` | user | fragment | `action` = `add_catalog` (`catalog_key`) / `add_custom` (`feed_url`, validated by one feedparser fetch, timeout 6 s, max 5) / `remove` (`id`) |
| POST | `/settings/comfort` | user | `204` + `HX-Refresh` | `text_size` ∈ S/M/L/XL, `theme` ∈ day/night/auto |
| GET | `/push/vapid-public-key` | user | JSON `{"key": "…"}` | F-21 |
| POST | `/push/subscribe` | user | `204` | JSON body = `PushSubscription.toJSON()`; upsert by endpoint; sets `profiles.notify = true` |
| POST | `/push/unsubscribe` | user | `204` | deletes by endpoint; sets `notify = false` if none left |
| POST | `/push/test` | user, `APP_ENV=dev` | `204` | sends a test notification (demo) |
| GET | `/sw.js` | none | `application/javascript` | service worker from `static/sw.js`, header `Service-Worker-Allowed: /` |
| GET | `/health` | none | JSON `{"ok": true, "version": "<git sha>", "db": true, "pdf": true}` | used by the deploy agent: checks DB query + Playwright browser alive; `version` from env `GIT_SHA` |
| POST | `/dev/time-travel` | user, `APP_ENV=dev` | redirect | generates an edition for "tomorrow" (date + 1) to demo learning |

## Onboarding form fields (`POST /onboarding`)

| Field | Type | Rule |
|---|---|---|
| `edition_lang` | str | in `SUPPORTED_LANGS` |
| `source_langs` | list[str] | subset of `SUPPORTED_LANGS`, ≤ 3 |
| `topics` | list[str] | ≥ 3 keys from `topics.json` |
| `topic_level_<key>` | int 1–3 | → weight 0.4 / 0.7 / 1.0 |
| `custom_interests` | JSON list `[{label, query}]` | from Profiler chips, ≤ 5 |
| `taste` | JSON list `[{topic_key, vote}]` | vote ∈ `up`,`down`; ±0.15 to that topic before saving |
| `display_name` | str ≤ 40 | default from email local part |
| `city` | str ≤ 60 | optional |
| `timezone` | str | must be in `zoneinfo.available_timezones()`, else `UTC` |
| `reading_minutes` | 5/10/20 | |
| `favorite_sources` | JSON list `[catalog_key]` | keys in `sources.json` for the edition language or `en`, ≤ 10 |
| `custom_feeds` | JSON list `[url]` | ≤ 5, validated like `POST /sources` |
| `muted_keywords` | JSON list `[str]` | ≤ 30, 2–40 chars each |
| `notify` | bool | if true, the page has already subscribed via `/push/subscribe` |

## Session handling (`deps.py`)
- `require_user`: read `sb_access`; validate with `supabase.auth.get_user(token)`; on
  expiry use `sb_refresh` with `supabase.auth.refresh_session(refresh_token)` and reset
  cookies; else redirect to `/login`.
- Never trust a `user_id` from a form; always use the session user.
