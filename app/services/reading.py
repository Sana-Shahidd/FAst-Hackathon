"""Reading state of an edition: read marks, saves, signals and the page view (F-07, F-19, F-22).

Read state is derived from `signals` (no extra table); every query filters by `user_id`.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app import deps
from app.agents import editor
from app.models import Reader
from app.services import sources

READ_KINDS = ("open", "click")
FEEDBACK_KINDS = ("more_like", "less_like", "skip_source")
SIGNAL_KINDS = (*FEEDBACK_KINDS, "dwell")
MAX_DWELL_SECONDS = 3600.0
HOURS_BEFORE_DATE = 48  # older than this shows the date instead of "N hours ago"


async def _db(fn):
    return await asyncio.to_thread(fn)


# --------------------------------------------------------------- pure helpers


def read_ids_from_signals(rows: list[dict], valid_ids: set[str]) -> set[str]:
    """Edition-article ids that have an `open`/`click` signal (ids outside the edition ignored)."""
    return {
        row["edition_article_id"]
        for row in rows
        if row.get("kind") in READ_KINDS and row.get("edition_article_id") in valid_ids
    }


def age_hours(published_at: str | datetime | None, now: datetime | None = None) -> int:
    """Whole hours since publication, at least 1; `-1` when the story has no date."""
    if not published_at:
        return -1
    if isinstance(published_at, str):
        published_at = datetime.fromisoformat(published_at)
    now = now or datetime.now(UTC)
    return max(1, int((now - published_at).total_seconds() // 3600))


def printed_time(ready_at: str | None, timezone: str) -> str:
    """`06:02`: when the edition was printed, in the reader's timezone ("" while unknown)."""
    if not ready_at:
        return ""
    moment = datetime.fromisoformat(ready_at)
    try:
        moment = moment.astimezone(ZoneInfo(timezone))
    except Exception:  # noqa: BLE001 - an unknown zone falls back to UTC
        moment = moment.astimezone(UTC)
    return moment.strftime("%H:%M")


def toggled(saved: bool) -> bool:
    """The state after a tap on the bookmark."""
    return not saved


def initials(name: str) -> str:
    """Two-letter badge for a source without a catalog entry: `Al Jazeera` -> `AJ`."""
    words = [w for w in name.replace("-", " ").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def source_circles(favorites: list[dict]) -> list[dict]:
    """The "Your sources" row: name, initials and brand colour from the catalog when known."""
    circles = []
    for fav in favorites:
        entry = (
            sources.entry_for(fav["catalog_key"]) if fav.get("catalog_key") else None
        )
        circles.append(
            {
                "name": fav["name"],
                "initials": (entry or {}).get("initials") or initials(fav["name"]),
                "color": (entry or {}).get("color") or "#1E3A6B",
            }
        )
    return circles


def group_editions(rows: list[dict]) -> list[dict]:
    """Archive entries, newest date first: the newest version of each date plus its older versions."""
    by_day: dict[str, list[dict]] = {}
    for row in sorted(
        rows, key=lambda r: (r["edition_date"], r["version"]), reverse=True
    ):
        by_day.setdefault(row["edition_date"], []).append(row)
    return [
        {"day": day, "latest": versions[0], "older": versions[1:]}
        for day, versions in by_day.items()
    ]


def group_saved(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Saved stories grouped by edition date (newest date first), newest save first inside a date."""
    groups: dict[str, list[dict]] = {}
    for row in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        groups.setdefault(
            row["edition_articles"]["editions"]["edition_date"], []
        ).append(row)
    return sorted(groups.items(), key=lambda item: item[0], reverse=True)


def group_sections(
    articles: list[dict], section_order: list[str]
) -> list[tuple[str, list[dict]]]:
    """Sections in the edition's order, each with its articles by position; the lead is excluded."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for art in articles:
        if art["slot"] != "lead":
            groups[art["section"]].append(art)
    keys = [k for k in section_order if k in groups]
    keys += [k for k in groups if k not in keys]
    return [(k, sorted(groups[k], key=lambda a: a["position"])) for k in keys]


# ------------------------------------------------------------------- queries


async def owned_article(user_id: str, edition_article_id: str) -> dict | None:
    """One edition article with its story and edition, only if the edition is the reader's."""
    client = deps.supabase_admin()
    try:
        rows = await _db(
            lambda: (
                client.table("edition_articles")
                .select("*,articles(*),editions!inner(user_id,edition_date,lang)")
                .eq("id", edition_article_id)
                .eq("editions.user_id", user_id)
                .limit(1)
                .execute()
                .data
            )
        )
    except Exception:  # noqa: BLE001 - a malformed id is simply "not found"
        return None
    return rows[0] if rows else None


async def edition_articles(edition_id: str) -> list[dict]:
    client = deps.supabase_admin()
    return await _db(
        lambda: (
            client.table("edition_articles")
            .select("*,articles(*)")
            .eq("edition_id", edition_id)
            .order("position")
            .execute()
            .data
        )
    )


async def read_among(user_id: str, ids: set[str]) -> set[str]:
    """Which of these edition articles the reader has opened (one signals query)."""
    if not ids:
        return set()
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("signals")
            .select("kind,edition_article_id")
            .eq("user_id", user_id)
            .in_("kind", list(READ_KINDS))
            .in_("edition_article_id", list(ids))
            .execute()
            .data
        )
    )
    return read_ids_from_signals(rows, ids)


async def read_ids_for_edition(user_id: str, edition_id: str) -> set[str]:
    """Ids of this edition's articles the reader has opened."""
    ids = {a["id"] for a in await edition_articles(edition_id)}
    return await read_among(user_id, ids)


async def progress(user_id: str, edition_id: str) -> tuple[int, int]:
    """(articles read, articles in the edition)."""
    ids = {a["id"] for a in await edition_articles(edition_id)}
    return len(await read_among(user_id, ids)), len(ids)


async def saved_ids(user_id: str, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("saved_articles")
            .select("edition_article_id")
            .eq("user_id", user_id)
            .in_("edition_article_id", ids)
            .execute()
            .data
        )
    )
    return {r["edition_article_id"] for r in rows}


async def saved_stories(user_id: str) -> list[dict]:
    """The reader's saved stories with their headline, story and edition (newest save first)."""
    client = deps.supabase_admin()
    return await _db(
        lambda: (
            client.table("saved_articles")
            .select(
                "created_at,edition_article_id,"
                "edition_articles(id,headline,summary,editions(edition_date,lang),"
                "articles(source_name,image_url,url))"
            )
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
            .data
        )
    )


async def feedback_state(user_id: str, ids: list[str]) -> dict[str, set[str]]:
    """edition_article_id -> feedback kinds already given (so the ⋯ menu shows them pressed)."""
    if not ids:
        return {}
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("signals")
            .select("kind,edition_article_id")
            .eq("user_id", user_id)
            .in_("kind", list(FEEDBACK_KINDS))
            .in_("edition_article_id", ids)
            .execute()
            .data
        )
    )
    state: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        state[row["edition_article_id"]].add(row["kind"])
    return state


async def record_signal(
    user_id: str,
    edition_article_id: str | None,
    kind: str,
    value: float | None = None,
    *,
    once: bool = False,
) -> None:
    """Insert a signal; with `once`, skip it when the reader already gave this kind for the story."""
    client = deps.supabase_admin()
    if once:
        existing = await _db(
            lambda: (
                client.table("signals")
                .select("id")
                .eq("user_id", user_id)
                .eq("edition_article_id", edition_article_id)
                .eq("kind", kind)
                .limit(1)
                .execute()
                .data
            )
        )
        if existing:
            return
    row = {
        "user_id": user_id,
        "edition_article_id": edition_article_id,
        "kind": kind,
        "value": value,
    }
    await _db(lambda: client.table("signals").insert(row).execute())


async def toggle_saved(user_id: str, edition_article_id: str) -> bool:
    """Save or unsave a story of the reader's own edition; True = now saved.

    Raises `LookupError` when the story is not in one of the reader's editions.
    """
    article = await owned_article(user_id, edition_article_id)
    if article is None:
        raise LookupError(edition_article_id)
    client = deps.supabase_admin()
    now_saved = toggled(
        edition_article_id in await saved_ids(user_id, [edition_article_id])
    )
    if now_saved:
        row = {
            "user_id": user_id,
            "edition_article_id": edition_article_id,
            "article_id": article["article_id"],
        }
        await _db(
            lambda: (
                client.table("saved_articles")
                .upsert(row, on_conflict="user_id,edition_article_id")
                .execute()
            )
        )
        await record_signal(user_id, edition_article_id, "save", once=True)
    else:
        await _db(
            lambda: (
                client.table("saved_articles")
                .delete()
                .eq("user_id", user_id)
                .eq("edition_article_id", edition_article_id)
                .execute()
            )
        )
    return now_saved


# ----------------------------------------------------------------- page view


async def interest_labels(user_id: str) -> dict[str, str]:
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("interests")
            .select("id,topic_key,label")
            .eq("user_id", user_id)
            .execute()
            .data
        )
    )
    return {(r["topic_key"] or f"i_{r['id'][:8]}"): r["label"] for r in rows}


async def favorites(user_id: str) -> list[dict]:
    client = deps.supabase_admin()
    return await _db(
        lambda: (
            client.table("favorite_sources")
            .select("catalog_key,name")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
            .data
        )
    )


def section_titles(
    keys: list[str], lang: str, labels: dict[str, str]
) -> dict[str, str]:
    reader = Reader(lang=lang, labels=labels)
    return {key: editor.section_title(key, reader) for key in keys}


def decorate(
    art: dict,
    day: str,
    read: set[str],
    saved: set[str],
    feedback: dict[str, set[str]],
) -> dict:
    """Add what a card shows: age, read/saved flags, feedback already given, edition date."""
    art["day"] = day
    art["age"] = age_hours((art.get("articles") or {}).get("published_at"))
    art["read"] = art["id"] in read
    art["saved"] = art["id"] in saved
    art["feedback"] = feedback.get(art["id"], set())
    return art


async def card_state(user_id: str, art: dict) -> dict:
    """Decorate one `owned_article` row with the reader's current state."""
    ids = [art["id"]]
    read = await read_among(user_id, set(ids))
    saved = await saved_ids(user_id, ids)
    feedback = await feedback_state(user_id, ids)
    return decorate(art, art["editions"]["edition_date"], read, saved, feedback)


async def load_view(user_id: str, edition: dict) -> dict[str, Any]:
    """Everything `edition.html` needs for one ready edition."""
    articles = await edition_articles(edition["id"])
    ids = [a["id"] for a in articles]
    read = await read_among(user_id, set(ids))
    saved = await saved_ids(user_id, ids)
    feedback = await feedback_state(user_id, ids)
    labels = await interest_labels(user_id)
    favs = await favorites(user_id)
    for art in articles:
        decorate(art, edition["edition_date"], read, saved, feedback)
    lead = next((a for a in articles if a["slot"] == "lead"), None)
    sections = group_sections(articles, edition.get("section_order") or [])
    titles = section_titles([key for key, _ in sections], edition["lang"], labels)
    return {
        "lead": lead,
        "sections": [(key, titles[key], items) for key, items in sections],
        "read_count": len(read),
        "total": len(articles),
        "circles": source_circles(favs),
    }
