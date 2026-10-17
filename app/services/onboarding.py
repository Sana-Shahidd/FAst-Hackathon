"""Onboarding: form validation, taste-test headlines and saving the reader (F-02)."""

from __future__ import annotations

import asyncio
import json
import zoneinfo
from datetime import UTC, datetime
from typing import Any

from app import deps
from app.agents.profiler import clean
from app.config import (
    MAX_CUSTOM_FEEDS,
    MAX_MUTES,
    READING_TIME_ARTICLES,
    SUPPORTED_LANGS,
    WEIGHT_MAX,
    WEIGHT_MIN,
)
from app.models import FeedUrl, OnboardingData, ParsedInterest, TopicChoice
from app.services import feeds, i18n, sources

LEVEL_WEIGHT = {1: 0.4, 2: 0.7, 3: 1.0}  # "a little / a lot / obsessed"
TASTE_STEP = 0.15
CUSTOM_WEIGHT = 0.7
MIN_TOPICS = 3
MAX_SOURCE_LANGS = 3
MAX_FAVORITES = 10
TASTE_CARDS = 8
TASTE_TIMEOUT_S = 5


class OnboardingError(ValueError):
    """A form problem the reader can fix; `key` is the i18n key of the message."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _json_list(form: Any, name: str) -> list:
    try:
        value = json.loads(form.get(name) or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _level(form: Any, key: str) -> int:
    try:
        level = int(form.get(f"topic_level_{key}") or 2)
    except ValueError:
        return 2
    return level if level in LEVEL_WEIGHT else 2


def _clamp(weight: float) -> float:
    return round(min(WEIGHT_MAX, max(WEIGHT_MIN, weight)), 2)


def parse_onboarding(form: Any) -> OnboardingData:
    """Validate the whole onboarding form; raises `OnboardingError` for fixable problems.

    Pure: custom feed URLs are only shape-checked here, the network check happens in the route.
    """
    lang = form.get("edition_lang", "en")
    lang = lang if lang in SUPPORTED_LANGS else "en"
    extra = [
        x
        for x in dict.fromkeys(form.getlist("source_langs"))
        if x in SUPPORTED_LANGS and x != lang
    ]
    known_topics = feeds.topics()
    picked = [k for k in dict.fromkeys(form.getlist("topics")) if k in known_topics]
    if len(picked) < MIN_TOPICS:
        raise OnboardingError("ob.topics.min")

    taste: dict[str, float] = {}
    for item in _json_list(form, "taste"):
        if isinstance(item, dict) and item.get("topic_key") in picked:
            delta = {"up": TASTE_STEP, "down": -TASTE_STEP}.get(item.get("vote"), 0.0)
            taste[item["topic_key"]] = round(
                taste.get(item["topic_key"], 0.0) + delta, 2
            )

    custom = clean(
        [
            ParsedInterest(label=str(i.get("label", "")), query=str(i.get("query", "")))
            for i in _json_list(form, "custom_interests")
            if isinstance(i, dict)
        ]
    )
    allowed = {o["key"] for o in sources.catalog_for(lang)}
    favorites = [
        k for k in dict.fromkeys(_json_list(form, "favorite_sources")) if k in allowed
    ]
    feed_urls = [
        u.strip()
        for u in dict.fromkeys(_json_list(form, "custom_feeds"))
        if isinstance(u, str) and u.strip().lower().startswith(("http://", "https://"))
    ]
    mutes = [
        m
        for m in dict.fromkeys(
            str(m).strip().lower() for m in _json_list(form, "muted_keywords")
        )
        if 2 <= len(m) <= 40
    ]
    try:
        minutes = int(form.get("reading_minutes") or 10)
    except ValueError:
        minutes = 10
    zone = (form.get("timezone") or "UTC").strip()
    return OnboardingData(
        edition_lang=lang,
        source_langs=extra[:MAX_SOURCE_LANGS],
        topics=[
            TopicChoice(key=k, weight=LEVEL_WEIGHT[_level(form, k)]) for k in picked
        ],
        custom_interests=custom,
        taste=taste,
        display_name=(form.get("display_name") or "").strip()[:40] or None,
        city=(form.get("city") or "").strip()[:60] or None,
        timezone=zone if zone in zoneinfo.available_timezones() else "UTC",
        reading_minutes=minutes if minutes in READING_TIME_ARTICLES else 10,
        favorite_sources=favorites[:MAX_FAVORITES],
        custom_feeds=feed_urls[:MAX_CUSTOM_FEEDS],
        muted_keywords=mutes[:MAX_MUTES],
        notify=str(form.get("notify", "")).lower() in {"1", "true", "on", "yes"},
    )


def final_weights(data: OnboardingData) -> dict[str, tuple[float, float]]:
    """topic key -> (weight from "how much", weight after the taste test)."""
    return {
        t.key: (t.weight, _clamp(t.weight + data.taste.get(t.key, 0.0)))
        for t in data.topics
    }


# ------------------------------------------------------------------ taste test


async def taste_cards(
    topic_keys: list[str], lang: str, limit: int = TASTE_CARDS
) -> list[dict]:
    """Up to `limit` real recent headlines across the chosen topics, one topic at a time."""
    keys = [k for k in dict.fromkeys(topic_keys) if k in feeds.topics()][:limit]
    urls = [
        FeedUrl(
            url=feeds.google_news_url(feeds.topic_query(k, lang), lang),
            lang=lang,
            kind="topic",
            topic_key=k,
        )
        for k in keys
    ]
    try:
        cands = await asyncio.wait_for(feeds.fetch_all(urls), TASTE_TIMEOUT_S + 1)
    except TimeoutError:
        return []
    fresh = feeds.filter_fresh(cands, 72) or cands
    per_topic = {
        k: [c for c in feeds.dedupe(fresh, []) if c.topic_key == k] for k in keys
    }
    cards: list[dict] = []
    for rank in range(limit):
        for key in keys:
            if rank < len(per_topic[key]) and len(cards) < limit:
                c = per_topic[key][rank]
                cards.append(
                    {"topic_key": key, "title": c.title, "source": c.source_name}
                )
    return cards


# ---------------------------------------------------------------------- saving


def _save(client: Any, user_id: str, data: OnboardingData, email: str | None) -> None:
    lang = data.edition_lang
    weights = final_weights(data)
    topic_rows = [
        {
            "user_id": user_id,
            "label": i18n.t(f"topic.{t.key}", lang)[:60],
            "topic_key": t.key,
            "query": feeds.topics()[t.key]["query"][:200],
            "weight": weights[t.key][1],
            "source": "onboarding",
        }
        for t in data.topics
    ]
    taken = {r["label"].lower() for r in topic_rows}
    custom_rows = [
        {
            "user_id": user_id,
            "label": c.label,
            "topic_key": None,
            "query": c.query,
            "weight": CUSTOM_WEIGHT,
            "source": "custom",
        }
        for c in data.custom_interests
        if c.label.lower() not in taken
    ]
    client.table("interests").delete().eq("user_id", user_id).execute()
    stored = client.table("interests").insert(topic_rows + custom_rows).execute().data
    by_key = {r["topic_key"]: r["id"] for r in stored if r.get("topic_key")}
    history = [
        {
            "interest_id": by_key[key],
            "old_weight": before,
            "new_weight": after,
            "reason": "taste_test",
        }
        for key, (before, after) in weights.items()
        if before != after and key in by_key
    ]
    if history:
        client.table("interest_history").insert(history).execute()

    client.table("favorite_sources").delete().eq("user_id", user_id).execute()
    favorite_rows = []
    for key in data.favorite_sources:
        outlet = sources.entry_for(key)
        if outlet:
            favorite_rows.append(
                {
                    "user_id": user_id,
                    "catalog_key": key,
                    "name": outlet["name"][:60],
                    "feed_url": outlet["feed_url"],
                    "kind": "catalog",
                }
            )
    favorite_rows += [
        {
            "user_id": user_id,
            "catalog_key": None,
            "name": name[:60],
            "feed_url": url,
            "kind": "custom",
        }
        for url, name in data.custom_feed_names.items()
    ]
    if favorite_rows:
        client.table("favorite_sources").insert(favorite_rows).execute()

    client.table("muted_keywords").delete().eq("user_id", user_id).execute()
    if data.muted_keywords:
        client.table("muted_keywords").insert(
            [{"user_id": user_id, "keyword": m} for m in data.muted_keywords]
        ).execute()

    profile = {
        "user_id": user_id,
        "edition_lang": lang,
        "source_langs": data.source_langs,
        "city": data.city,
        "timezone": data.timezone,
        "reading_minutes": data.reading_minutes,
        "notify": data.notify,
        "display_name": data.display_name or (email or "Reader").split("@")[0][:40],
        "onboarded_at": datetime.now(
            UTC
        ).isoformat(),  # last: a failed save stays in onboarding
    }
    client.table("profiles").upsert(profile, on_conflict="user_id").execute()


async def save_onboarding(
    user_id: str, data: OnboardingData, email: str | None = None
) -> None:
    """Write profile, interests (+ taste history), favorites and mutes; idempotent."""
    await asyncio.to_thread(_save, deps.supabase_admin(), user_id, data, email)
