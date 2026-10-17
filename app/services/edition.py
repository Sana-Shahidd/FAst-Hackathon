"""The edition pipeline: fetch -> curate -> write -> lay out -> save (docs/02_PRD.md F-05).

Every LLM step has a deterministic fallback, so `generate_edition` only fails when there is
nothing to print at all (no stories from any feed).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app import deps
from app.agents import curator, editor
from app.config import (
    FRESH_HOURS,
    FRESH_HOURS_FALLBACK,
    MAX_CANDIDATES,
    READING_TIME_ARTICLES,
    RECENT_EDITIONS_EXCLUDE,
)
from app.models import Candidate, FavoriteSource, Interest, Profile, Reader
from app.services import activity, feeds, layout, learning, mutes, puzzle

logger = logging.getLogger(__name__)

MIN_CANDIDATES = 8  # below this the pipeline widens the net (docs/03_TECH.md §7)
ENOUGH_FRESH = 30  # fewer fresh stories than this -> accept up to 72 h old


class NothingToPrint(RuntimeError):
    """No usable story came back from any feed."""


async def _db(fn):
    return await asyncio.to_thread(fn)


def local_date_for(timezone: str, now: datetime | None = None) -> date:
    """The reader's calendar date right now."""
    now = now or datetime.now(UTC)
    try:
        return now.astimezone(ZoneInfo(timezone)).date()
    except Exception:  # noqa: BLE001 - an unknown zone must not break the paper
        return now.date()


# ----------------------------------------------------------------- loading


async def get_profile(user_id: str) -> Profile | None:
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("profiles")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
        )
    )
    return Profile(**rows[0]) if rows else None


async def is_onboarded(user_id: str) -> bool:
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("profiles")
            .select("onboarded_at")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
        )
    )
    return bool(rows and rows[0].get("onboarded_at"))


async def profile_today(user_id: str) -> tuple[Profile | None, date | None]:
    """(profile, the reader's local date); profile is None until onboarding is finished."""
    profile = await get_profile(user_id)
    if profile is None or not await is_onboarded(user_id):
        return None, None
    return profile, local_date_for(profile.timezone)


async def _feedback(client, user_id: str) -> tuple[list[str], list[str], list[str]]:
    """(liked headlines, disliked headlines, blocked source names) from recent signals."""
    signals = await _db(
        lambda: (
            client.table("signals")
            .select("kind,edition_article_id")
            .eq("user_id", user_id)
            .in_("kind", ["more_like", "less_like", "skip_source"])
            .order("created_at", desc=True)
            .limit(60)
            .execute()
            .data
        )
    )
    ids = [s["edition_article_id"] for s in signals if s.get("edition_article_id")]
    if not ids:
        return [], [], []
    rows = await _db(
        lambda: (
            client.table("edition_articles")
            .select("id,headline,articles(source_name)")
            .in_("id", ids)
            .execute()
            .data
        )
    )
    info = {r["id"]: r for r in rows}
    liked, disliked, blocked = [], [], []
    for sig in signals:
        row = info.get(sig.get("edition_article_id"))
        if not row:
            continue
        if sig["kind"] == "more_like":
            liked.append(row["headline"])
        elif sig["kind"] == "less_like":
            disliked.append(row["headline"])
        elif source := (row.get("articles") or {}).get("source_name"):
            blocked.append(source)
    return liked[:10], disliked[:10], list(dict.fromkeys(blocked))


async def _recent(client, user_id: str) -> tuple[set[str], list[str]]:
    """URL hashes and titles of stories in the reader's last few editions."""
    editions = await _db(
        lambda: (
            client.table("editions")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "ready")
            .order("edition_date", desc=True)
            .limit(RECENT_EDITIONS_EXCLUDE)
            .execute()
            .data
        )
    )
    if not editions:
        return set(), []
    rows = await _db(
        lambda: (
            client.table("edition_articles")
            .select("articles(title,url_hash)")
            .in_("edition_id", [e["id"] for e in editions])
            .execute()
            .data
        )
    )
    articles = [r["articles"] for r in rows if r.get("articles")]
    return {a["url_hash"] for a in articles}, [a["title"] for a in articles]


def build_reader(
    profile: Profile,
    interests: list[Interest],
    favorites: list[FavoriteSource],
    liked: list[str],
    disliked: list[str],
    blocked: list[str],
    lang: str,
) -> Reader:
    weights: dict[str, float] = {}
    labels: dict[str, str] = {}
    for interest in interests:
        key = interest.topic_key or f"i_{interest.id[:8]}"
        weights[key] = max(weights.get(key, 0.0), interest.weight)
        labels[key] = interest.label
    return Reader(
        lang=lang,
        name=profile.display_name,
        n=READING_TIME_ARTICLES.get(profile.reading_minutes, 14),
        city=profile.city,
        weights=weights,
        labels=labels,
        favorite_sources=[f.name for f in favorites],
        blocked_sources=blocked,
        liked=liked,
        disliked=disliked,
    )


# -------------------------------------------------------------- candidates


def balance(cands: list[Candidate], limit: int = MAX_CANDIDATES) -> list[Candidate]:
    """At most `limit` candidates: favorites first, then newest-first round-robin over sections."""
    favorites = [c for c in cands if c.favorite]
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for cand in cands:
        if not cand.favorite:
            groups[cand.section].append(cand)
    for items in groups.values():
        items.sort(
            key=lambda c: c.published_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
    chosen = favorites[:limit]
    rank = 0
    while len(chosen) < limit and any(rank < len(items) for items in groups.values()):
        for items in groups.values():
            if rank < len(items) and len(chosen) < limit:
                chosen.append(items[rank])
        rank += 1
    return chosen


def prepare(
    cands: list[Candidate],
    keywords: list[str],
    lang: str,
    seen_hashes: set[str],
    seen_titles: list[str],
) -> tuple[list[Candidate], dict[str, int]]:
    """Freshness -> mutes -> already-seen -> dedupe; returns the survivors and what was dropped."""
    fresh = feeds.filter_fresh(cands, FRESH_HOURS)
    if len(fresh) < ENOUGH_FRESH:
        fresh = feeds.filter_fresh(cands, FRESH_HOURS_FALLBACK)
    kept, muted = mutes.filter_muted(fresh, keywords, lang)
    unseen = [c for c in kept if c.url_hash not in seen_hashes]
    final = feeds.dedupe(unseen, seen_titles)
    return final, {
        "muted": muted,
        "seen": len(kept) - len(unseen),
        "duplicates": len(unseen) - len(final),
    }


# ---------------------------------------------------------------- pipeline


async def generate_edition(
    user_id: str, local_date: date, *, lang: str | None = None, regenerate: bool = False
) -> str:
    """Build (or rebuild) the reader's paper for `local_date`; returns the edition id."""
    client = deps.supabase_admin()
    existing = await _db(
        lambda: (
            client.table("editions")
            .select("id,version,edition_no,status")
            .eq("user_id", user_id)
            .eq("edition_date", local_date.isoformat())
            .order("version", desc=True)
            .limit(1)
            .execute()
            .data
        )
    )
    if existing and not regenerate and existing[0]["status"] in ("ready", "generating"):
        return existing[0]["id"]
    profile = await get_profile(user_id)
    if profile is None:
        raise LookupError("no profile for this user")
    edition_lang = lang or profile.edition_lang
    if existing:
        version, edition_no = existing[0]["version"] + 1, existing[0]["edition_no"]
    else:
        latest = await _db(
            lambda: (
                client.table("editions")
                .select("edition_no")
                .eq("user_id", user_id)
                .order("edition_no", desc=True)
                .limit(1)
                .execute()
                .data
            )
        )
        version, edition_no = 1, (latest[0]["edition_no"] + 1 if latest else 1)
    row = {
        "user_id": user_id,
        "edition_date": local_date.isoformat(),
        "version": version,
        "edition_no": edition_no,
        "lang": edition_lang,
        "status": "generating",
    }
    edition_id = (
        await _db(lambda: client.table("editions").insert(row).execute().data)
    )[0]["id"]
    started = time.monotonic()
    try:
        await _run(
            client,
            user_id,
            edition_id,
            profile,
            edition_lang,
            local_date,
            version,
            started,
        )
    except Exception as exc:
        logger.exception("edition %s failed", edition_id)
        message = (
            "Nothing to print today"
            if isinstance(exc, NothingToPrint)
            else f"Failed: {type(exc).__name__}"
        )
        await activity.log(edition_id, "pipeline", "error", message)
        await _db(
            lambda: (
                client.table("editions")
                .update({"status": "failed"})
                .eq("id", edition_id)
                .execute()
            )
        )
    return edition_id


async def _run(
    client, user_id, edition_id, profile, lang, local_date, version, started
) -> None:
    try:
        await learning.maybe_run_learner(user_id, edition_id)
    except Exception:
        logger.warning("learner failed for edition %s", edition_id, exc_info=True)
    interests_rows = await _db(
        lambda: (
            client.table("interests")
            .select("*")
            .eq("user_id", user_id)
            .eq("active", True)
            .execute()
            .data
        )
    )
    favorite_rows = await _db(
        lambda: (
            client.table("favorite_sources")
            .select("*")
            .eq("user_id", user_id)
            .execute()
            .data
        )
    )
    mute_rows = await _db(
        lambda: (
            client.table("muted_keywords")
            .select("keyword")
            .eq("user_id", user_id)
            .execute()
            .data
        )
    )
    interests = [Interest(**r) for r in interests_rows]
    favorites = [FavoriteSource(**r) for r in favorite_rows]
    keywords = [r["keyword"] for r in mute_rows]
    liked, disliked, blocked = await _feedback(client, user_id)
    seen_hashes, seen_titles = await _recent(client, user_id)
    reader = build_reader(profile, interests, favorites, liked, disliked, blocked, lang)
    await activity.log(
        edition_id, "pipeline", "started", f"Building {reader.name}'s edition"
    )

    urls = feeds.build_feed_urls(
        profile.model_copy(update={"edition_lang": lang}), interests, favorites
    )
    cands, ok, failed = await feeds.fetch_all_with_stats(urls)
    await activity.log(
        edition_id,
        "pipeline",
        "stat",
        f"Fetched {ok} feeds → {len(cands)} stories ({failed} feeds failed)",
    )
    final, dropped = prepare(cands, keywords, lang, seen_hashes, seen_titles)
    if len(final) < MIN_CANDIDATES:
        extra, extra_ok, _ = await feeds.fetch_all_with_stats(
            feeds.english_fallback_urls(interests)
        )
        ok += extra_ok
        final, dropped = prepare(
            [*cands, *extra], keywords, lang, seen_hashes, seen_titles
        )
        await activity.log(
            edition_id,
            "pipeline",
            "stat",
            f"Quiet news day: added English searches → {len(final)} stories",
        )
    if not final:
        raise NothingToPrint
    await activity.log(
        edition_id,
        "pipeline",
        "stat",
        f"Removed {dropped['duplicates']} duplicates, {dropped['seen']} seen in earlier editions, "
        f"{dropped['muted']} muted → {len(final)} candidates",
        {"muted": dropped["muted"]},
    )
    cands = balance(final, MAX_CANDIDATES)
    by_id = {c.id: c for c in cands}

    picks, curator_fallback, notes = await curator.pick(cands, reader, edition_id)
    sections = layout.order_sections(picks, reader.weights)
    placed = layout.arrange(layout.assign_slots(picks), sections)
    lead = by_id[next(p.candidate_id for p in placed if p.slot == "lead")]
    await activity.log(
        edition_id,
        "curator",
        "decision",
        f'Picked {len(picks)} stories across {len(sections)} sections; lead: "{lead.title[:120]}"',
        {"notes": notes},
    )
    written, editor_out = await editor.write(
        picks, by_id, reader, edition_id, local_date
    )
    if written.gaps:
        await activity.log(
            edition_id,
            "editor",
            "fallback",
            f"Wrote {len(written.gaps)} articles with fallback text",
        )
    headlines = {cid: text[0] for cid, text in written.articles.items()}
    items = puzzle.items_from_editor(editor_out, placed, headlines, lang)
    from_editor = sum(1 for i in items if i["source"] == "editor")
    await activity.log(
        edition_id,
        "editor",
        "stat",
        f"Puzzle: {from_editor} items from the Editor, {len(items) - from_editor} built by code",
    )
    await _save(
        client,
        edition_id,
        user_id,
        local_date,
        version,
        placed,
        by_id,
        written,
        sections,
        items,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    used_fallback = curator_fallback or written.used_fallback
    await _db(
        lambda: (
            client.table("editions")
            .update(
                {
                    "status": "ready",
                    "lead_headline": written.lead_headline,
                    "lead_dek": written.lead_dek,
                    "editor_note": written.editor_note,
                    "three_things": written.three_things,
                    "section_order": sections,
                    "used_fallback": used_fallback,
                    "generation_ms": elapsed_ms,
                    "sources_count": ok,
                    "ready_at": datetime.now(UTC).isoformat(),
                }
            )
            .eq("id", edition_id)
            .execute()
        )
    )
    await _db(
        lambda: (
            client.table("editions")
            .update({"status": "superseded"})
            .eq("user_id", user_id)
            .eq("edition_date", local_date.isoformat())
            .lt("version", version)
            .execute()
        )
    )
    await activity.log(
        edition_id,
        "pipeline",
        "finished",
        f"Edition ready in {elapsed_ms / 1000:.1f} s",
        {"ms": elapsed_ms},
    )


async def _save(
    client,
    edition_id,
    user_id,
    local_date,
    version,
    placed,
    by_id,
    written,
    sections,
    items,
) -> None:
    """Upsert the picked stories, then the edition's articles and puzzle."""
    chosen = [by_id[p.candidate_id] for p in placed]
    article_rows = [
        {
            "url": c.url,
            "url_hash": c.url_hash,
            "title": c.title,
            "source_name": c.source_name,
            "summary": c.summary,
            "image_url": c.image_url,
            "lang": c.lang,
            "published_at": c.published_at.isoformat() if c.published_at else None,
        }
        for c in chosen
    ]
    stored = await _db(
        lambda: (
            client.table("articles")
            .upsert(article_rows, on_conflict="url_hash")
            .execute()
            .data
        )
    )
    article_id = {a["url_hash"]: a["id"] for a in stored}
    rows = []
    for p in placed:
        c = by_id[p.candidate_id]
        headline, summary, why = written.articles[p.candidate_id]
        rows.append(
            {
                "edition_id": edition_id,
                "article_id": article_id[c.url_hash],
                "section": p.section,
                "slot": p.slot,
                "position": p.position,
                "headline": headline,
                "summary": summary,
                "why": why,
                "topic_key": c.topic_key,
                "interest_id": c.interest_id,
            }
        )
    saved = await _db(
        lambda: client.table("edition_articles").insert(rows).execute().data
    )
    by_article = {r["article_id"]: r["id"] for r in saved}
    puzzle_items = [
        {
            "edition_article_id": by_article[
                article_id[by_id[i["candidate_id"]].url_hash]
            ],
            "masked_headline": i["masked_headline"],
            "answer": i["answer"],
            "choices": i["choices"],
        }
        for i in items
    ]
    if puzzle_items:
        await _db(
            lambda: (
                client.table("puzzles")
                .upsert(
                    {"edition_id": edition_id, "items": puzzle_items},
                    on_conflict="edition_id",
                )
                .execute()
            )
        )


# ---------------------------------------------------------- background runs

_running: dict[str, asyncio.Task] = {}
_baseline: dict[str, int] = {}  # newest version the reader had when the run started


def _forget(user_id: str) -> None:
    _running.pop(user_id, None)
    _baseline.pop(user_id, None)


async def start_generation(
    user_id: str, local_date: date, *, lang: str | None = None, regenerate: bool = False
) -> asyncio.Task:
    """Run `generate_edition` in the background; one run per reader at a time."""
    running = _running.get(user_id)
    if running is not None and not running.done():
        return running
    latest = await latest_edition(user_id, local_date)
    _baseline[user_id] = latest["version"] if latest else 0
    task = asyncio.create_task(
        generate_edition(user_id, local_date, lang=lang, regenerate=regenerate)
    )
    _running[user_id] = task
    task.add_done_callback(lambda t: _forget(user_id))
    return task


def regenerating(user_id: str, latest: dict | None) -> bool:
    """True while a run is going but its new version row does not exist yet.

    Without this, the printing page of a regeneration would see the old *ready* version and
    bounce straight back to the paper.
    """
    running = _running.get(user_id)
    return bool(
        latest
        and running is not None
        and not running.done()
        and latest["version"] == _baseline.get(user_id)
    )


async def latest_edition(user_id: str, local_date: date) -> dict | None:
    """Newest version of the reader's edition for a date (any status), or None."""
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("editions")
            .select("*")
            .eq("user_id", user_id)
            .eq("edition_date", local_date.isoformat())
            .order("version", desc=True)
            .limit(1)
            .execute()
            .data
        )
    )
    return rows[0] if rows else None


async def ready_edition(
    user_id: str, local_date: date, version: int | None = None
) -> dict | None:
    """Newest *ready* version for a date; during a regeneration the old one stays visible.

    With `version`, that exact version if it is finished (ready, or superseded by a newer one).
    """
    client = deps.supabase_admin()
    statuses = ["ready", "superseded"] if version is not None else ["ready"]
    query = (
        client.table("editions")
        .select("*")
        .eq("user_id", user_id)
        .eq("edition_date", local_date.isoformat())
        .in_("status", statuses)
    )
    if version is not None:
        query = query.eq("version", version)
    rows = await _db(lambda: query.order("version", desc=True).limit(1).execute().data)
    return rows[0] if rows else None


async def list_editions(user_id: str) -> list[dict]:
    """Every finished edition (ready or superseded) of the reader, newest date first."""
    client = deps.supabase_admin()
    return await _db(
        lambda: (
            client.table("editions")
            .select(
                "id,edition_date,version,edition_no,lang,status,lead_headline,"
                "lead_dek,pdf_path,ready_at"
            )
            .eq("user_id", user_id)
            .in_("status", ["ready", "superseded"])
            .order("edition_date", desc=True)
            .order("version", desc=True)
            .execute()
            .data
        )
    )


async def steps_for(edition_id: str) -> list[dict]:
    """The live progress lines shown while printing (and later on "How this paper was made")."""
    client = deps.supabase_admin()
    return await _db(
        lambda: (
            client.table("agent_activity")
            .select("agent,kind,message,created_at")
            .eq("edition_id", edition_id)
            .order("created_at")
            .execute()
            .data
        )
    )
