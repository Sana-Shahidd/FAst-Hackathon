"""Reader preferences: settings, mute words and favorite sources (docs/02_PRD.md F-18, F-23, F-20).

Every query filters by `user_id` (AGENTS.md Rule 3); the synchronous Supabase client runs in a thread.
"""

from __future__ import annotations

import asyncio
import re
import zoneinfo
from datetime import time

from app import deps
from app.config import (
    MAX_CUSTOM_FEEDS,
    MAX_MUTES,
    READING_TIME_ARTICLES,
    SUPPORTED_LANGS,
)
from app.services import sources

MAX_FAVORITES = 10
MIN_MUTE, MAX_MUTE = 2, 40
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class PrefsError(ValueError):
    """A fixable problem; `key` is the i18n key of the message shown to the reader."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


async def _db(fn):
    return await asyncio.to_thread(fn)


# --------------------------------------------------------------------- pure


def clean_mute(word: str) -> str | None:
    """A mute word lower-cased and trimmed, or None when it is not 2-40 characters."""
    word = " ".join(word.split()).lower()
    return word if MIN_MUTE <= len(word) <= MAX_MUTE else None


def parse_delivery_time(value: str) -> time | None:
    match = _TIME.match(value.strip())
    return time(int(match.group(1)), int(match.group(2))) if match else None


def validate_settings(form: dict) -> dict:
    """Validated `profiles` columns from the settings form; raises `PrefsError`."""
    lang = form.get("edition_lang", "en")
    if lang not in SUPPORTED_LANGS:
        raise PrefsError("auth.error.generic")
    try:
        minutes = int(form.get("reading_minutes") or 10)
    except ValueError:
        raise PrefsError("auth.error.generic") from None
    if minutes not in READING_TIME_ARTICLES:
        raise PrefsError("auth.error.generic")
    zone = (form.get("timezone") or "UTC").strip()
    if zone not in zoneinfo.available_timezones():
        raise PrefsError("auth.error.generic")
    delivery = parse_delivery_time(form.get("delivery_time") or "06:00")
    if delivery is None:
        raise PrefsError("auth.error.generic")
    return {
        "display_name": (form.get("display_name") or "").strip()[:40] or "Reader",
        "edition_lang": lang,
        "city": (form.get("city") or "").strip()[:60] or None,
        "timezone": zone,
        "reading_minutes": minutes,
        "delivery_time": delivery.strftime("%H:%M"),
        "notify": str(form.get("notify", "")).lower() in {"1", "true", "on", "yes"},
    }


# ------------------------------------------------------------------ settings


async def get_settings(user_id: str) -> dict:
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("profiles")
            .select(
                "display_name,edition_lang,city,timezone,reading_minutes,delivery_time,notify,"
                "text_size,theme"
            )
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
        )
    )
    row = dict(rows[0]) if rows else {}
    row["delivery_time"] = str(row.get("delivery_time") or "06:00")[:5]
    return row


async def save_settings(user_id: str, form: dict) -> None:
    values = validate_settings(form)
    client = deps.supabase_admin()
    await _db(
        lambda: client.table("profiles").update(values).eq("user_id", user_id).execute()
    )


# --------------------------------------------------------------------- mutes


async def list_mutes(user_id: str) -> list[str]:
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("muted_keywords")
            .select("keyword")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
            .data
        )
    )
    return [r["keyword"] for r in rows]


async def add_mute(user_id: str, word: str) -> None:
    """Add a mute word (2-40 characters, at most 30 words); re-adding one is harmless."""
    keyword = clean_mute(word)
    if keyword is None:
        raise PrefsError("settings.mute_length")
    current = await list_mutes(user_id)
    if keyword not in current and len(current) >= MAX_MUTES:
        raise PrefsError("settings.mute_limit")
    row = {"user_id": user_id, "keyword": keyword}
    client = deps.supabase_admin()
    await _db(
        lambda: (
            client.table("muted_keywords")
            .upsert(row, on_conflict="user_id,keyword")
            .execute()
        )
    )


async def remove_mute(user_id: str, word: str) -> None:
    keyword = " ".join(word.split()).lower()
    client = deps.supabase_admin()
    await _db(
        lambda: (
            client.table("muted_keywords")
            .delete()
            .eq("user_id", user_id)
            .eq("keyword", keyword)
            .execute()
        )
    )


# ------------------------------------------------------------------- sources


async def list_favorites(user_id: str) -> list[dict]:
    client = deps.supabase_admin()
    return await _db(
        lambda: (
            client.table("favorite_sources")
            .select("id,catalog_key,name,feed_url,kind")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
            .data
        )
    )


async def add_catalog_source(user_id: str, key: str, lang: str) -> None:
    """Add an outlet from the catalog offered for the reader's language."""
    outlet = sources.entry_for(key)
    if outlet is None or key not in {o["key"] for o in sources.catalog_for(lang)}:
        raise PrefsError("sources.invalid")
    favorites = await list_favorites(user_id)
    if len(favorites) >= MAX_FAVORITES:
        raise PrefsError("settings.sources_limit")
    row = {
        "user_id": user_id,
        "catalog_key": key,
        "name": outlet["name"][:60],
        "feed_url": outlet["feed_url"],
        "kind": "catalog",
    }
    client = deps.supabase_admin()
    await _db(
        lambda: (
            client.table("favorite_sources")
            .upsert(row, on_conflict="user_id,feed_url")
            .execute()
        )
    )


async def add_custom_source(user_id: str, url: str) -> None:
    """Add a pasted RSS/Atom link after one validation fetch (max 5 custom feeds)."""
    favorites = await list_favorites(user_id)
    if (
        len(favorites) >= MAX_FAVORITES
        or sum(f["kind"] == "custom" for f in favorites) >= MAX_CUSTOM_FEEDS
    ):
        raise PrefsError("settings.sources_limit")
    ok, title = await sources.validate_custom_feed(url)
    if not ok:
        raise PrefsError("sources.invalid")
    row = {
        "user_id": user_id,
        "catalog_key": None,
        "name": (title or url)[:60],
        "feed_url": url.strip(),
        "kind": "custom",
    }
    client = deps.supabase_admin()
    await _db(
        lambda: (
            client.table("favorite_sources")
            .upsert(row, on_conflict="user_id,feed_url")
            .execute()
        )
    )


async def remove_source(user_id: str, source_id: str) -> None:
    client = deps.supabase_admin()
    try:
        await _db(
            lambda: (
                client.table("favorite_sources")
                .delete()
                .eq("id", source_id)
                .eq("user_id", user_id)
                .execute()
            )
        )
    except Exception:  # noqa: BLE001 - a malformed id removes nothing
        return
