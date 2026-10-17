"""Feed URLs, parallel fetching, normalisation and dedupe (docs/02_PRD.md F-03, F-04)."""

from __future__ import annotations

import asyncio
import html
import json
import re
from calendar import timegm
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import cache
from html.parser import HTMLParser
from urllib.parse import urlencode

import feedparser
import httpx
from rapidfuzz import fuzz

from app.config import DEDUPE_THRESHOLD, FEED_TIMEOUT_S, MAX_FEED_URLS
from app.models import Candidate, FavoriteSource, FeedUrl, Interest, Profile
from app.services import i18n

GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search"
SUMMARY_MAX = 600
USER_AGENT = "Mozilla/5.0 (compatible; SubahBot/0.1; +https://github.com/Sana-Shahidd/FAst-Hackathon)"


@cache
def topics() -> dict[str, dict]:
    """`app/data/topics.json`: topic key -> emoji, icon, English query, local queries."""
    return json.loads((i18n.DATA_DIR / "topics.json").read_text(encoding="utf-8"))


@cache
def curated() -> dict[str, list[dict]]:
    """`app/data/feeds.json`: verified general feeds per language."""
    return json.loads((i18n.DATA_DIR / "feeds.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- URL building


def google_news_url(query: str, lang: str) -> str:
    """Google News RSS search URL with the edition's `hl`/`gl`/`ceid`."""
    gn = i18n.languages()[lang]["gn"]
    params = {"q": query, "hl": gn["hl"], "gl": gn["gl"], "ceid": gn["ceid"]}
    return f"{GOOGLE_NEWS_SEARCH}?{urlencode(params)}"


def topic_query(topic_key: str, lang: str) -> str:
    """Local-language query when `topics.json` has one, else the English query."""
    topic = topics()[topic_key]
    return topic.get("query_local", {}).get(lang) or topic["query"]


def _interest_feed(interest: Interest, lang: str) -> FeedUrl:
    if interest.topic_key and interest.topic_key in topics():
        query, kind = topic_query(interest.topic_key, lang), "topic"
    else:
        query, kind = interest.query, "interest"
    return FeedUrl(
        url=google_news_url(query, lang),
        lang=lang,
        kind=kind,
        name=interest.label,
        topic_key=interest.topic_key,
        interest_id=interest.id or None,
    )


def _curated_feeds(lang: str) -> list[FeedUrl]:
    return [
        FeedUrl(
            url=f["url"],
            lang=lang,
            kind="curated",
            name=f["name"],
            topic_key=f["topic_key"],
        )
        for f in curated().get(lang, [])
    ]


def build_feed_urls(
    profile: Profile,
    interests: list[Interest],
    favorites: Sequence[FavoriteSource] = (),
) -> list[FeedUrl]:
    """Feeds for one edition, most important first, capped at `MAX_FEED_URLS`.

    Order: favorite and custom feeds (always fetched), interests by weight, the reader's
    city, curated general feeds, then the same interests and curated feeds in each extra
    source language.
    """
    lang = profile.edition_lang
    ranked = sorted((i for i in interests if i.active), key=lambda i: -i.weight)
    urls = [
        FeedUrl(
            url=f.feed_url,
            lang=lang,
            kind="custom" if f.kind == "custom" else "favorite",
            name=f.name,
            favorite=True,
        )
        for f in favorites
    ]
    urls += [_interest_feed(i, lang) for i in ranked]
    if profile.city:
        urls.append(
            FeedUrl(
                url=google_news_url(f'"{profile.city}"', lang),
                lang=lang,
                kind="city",
                name=profile.city,
                topic_key="your_city",
            )
        )
    urls += _curated_feeds(lang)
    for extra in dict.fromkeys(profile.source_langs):
        if extra != lang and extra in i18n.languages():
            urls += [_interest_feed(i, extra) for i in ranked[:3]]
            urls += _curated_feeds(extra)[:1]
    unique: dict[str, FeedUrl] = {}
    for feed in urls:
        unique.setdefault(feed.url, feed)
    return list(unique.values())[:MAX_FEED_URLS]


def english_fallback_urls(interests: list[Interest]) -> list[FeedUrl]:
    """English queries for the top interests, used when a language edition is thin."""
    ranked = sorted((i for i in interests if i.active), key=lambda i: -i.weight)
    return [_interest_feed(i, "en") for i in ranked[:5]]


# ------------------------------------------------------------- normalisation


class _TextExtractor(HTMLParser):
    """Collects text, skipping the contents of <script> and <style>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self._hidden += tag in ("script", "style")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def strip_html(text: str) -> str:
    """Plain text of an HTML fragment, whitespace collapsed."""
    parser = _TextExtractor()
    parser.feed(text or "")
    parser.close()
    return re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip()


def _truncate(text: str, limit: int = SUMMARY_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


# Letters used in Urdu but not in Arabic.
_URDU_LETTERS = set("ٹڈڑںےھگچپژ")


def detect_lang(text: str, requested: str) -> str:
    """Language of a headline from its script; Google News has no real `ur` edition."""
    arabic = deva = bengali = han = latin = 0
    for ch in text:
        cp = ord(ch)
        if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0xFB50 <= cp <= 0xFEFF:
            arabic += 1
        elif 0x0900 <= cp <= 0x097F:
            deva += 1
        elif 0x0980 <= cp <= 0x09FF:
            bengali += 1
        elif 0x4E00 <= cp <= 0x9FFF:
            han += 1
        elif ch.isalpha():
            latin += 1
    top = max(arabic, deva, bengali, han, latin)
    if top == 0 or top == latin:
        return requested if requested in ("en", "es", "fr") else "en"
    if top == deva:
        return "hi"
    if top == bengali:
        return "bn"
    if top == han:
        return "zh"
    if requested in ("ur", "ar"):
        return requested
    return "ur" if any(ch in _URDU_LETTERS for ch in text) else "ar"


def _published(entry: feedparser.FeedParserDict) -> datetime | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(timegm(stamp), UTC) if stamp else None


def _image(entry: feedparser.FeedParserDict) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key) or []:
            if media.get("url"):
                return media["url"]
    for enc in entry.get("enclosures") or []:
        if str(enc.get("type", "")).startswith("image/") and enc.get("href"):
            return enc["href"]
    return None


def normalise(parsed: feedparser.FeedParserDict, feed: FeedUrl) -> list[Candidate]:
    """Candidates from one parsed feed; entries without a title or http(s) link are dropped."""
    feed_title = strip_html(parsed.feed.get("title", "")) if parsed.get("feed") else ""
    out: list[Candidate] = []
    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = strip_html(entry.get("title", ""))
        if not title or not link.lower().startswith(("http://", "https://")):
            continue
        source = (
            strip_html(entry.get("source", {}).get("title", ""))
            or feed.name
            or feed_title
        )
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].rstrip()
        summary = strip_html(entry.get("summary", ""))
        if summary == title or summary.startswith(title):
            summary = ""  # Google News repeats the headline and source here
        out.append(
            Candidate(
                url=link,
                title=title,
                source_name=source,
                summary=_truncate(summary),
                image_url=_image(entry),
                lang=detect_lang(title, feed.lang),
                published_at=_published(entry),
                topic_key=feed.topic_key,
                interest_id=feed.interest_id,
                favorite=feed.favorite,
            )
        )
    return out


# ------------------------------------------------------------------- fetching


async def _fetch_one(client: httpx.AsyncClient, feed: FeedUrl) -> list[Candidate]:
    response = await asyncio.wait_for(client.get(feed.url), FEED_TIMEOUT_S)
    response.raise_for_status()
    return normalise(feedparser.parse(response.text), feed)


async def fetch_all_with_stats(urls: list[FeedUrl]) -> tuple[list[Candidate], int, int]:
    """(candidates, feeds ok, feeds failed); a failing feed is skipped, never fatal."""
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(
        timeout=FEED_TIMEOUT_S, follow_redirects=True, headers=headers
    ) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, feed) for feed in urls), return_exceptions=True
        )
    cands: list[Candidate] = []
    failed = 0
    for result in results:
        if isinstance(result, BaseException):
            failed += 1
        else:
            cands += result
    return cands, len(results) - failed, failed


async def fetch_all(urls: list[FeedUrl]) -> list[Candidate]:
    """All candidates from `urls`, fetched in parallel with a timeout per feed."""
    return (await fetch_all_with_stats(urls))[0]


def filter_fresh(
    cands: list[Candidate], hours: int, now: datetime | None = None
) -> list[Candidate]:
    """Candidates published within `hours`; undated items cannot be shown as fresh."""
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=hours)
    return [c for c in cands if c.published_at and c.published_at >= cutoff]


# --------------------------------------------------------------------- dedupe


def _rank(c: Candidate) -> tuple[bool, bool, int]:
    return (c.favorite, c.image_url is not None, len(c.summary))


def dedupe(cands: list[Candidate], recent_titles: list[str]) -> list[Candidate]:
    """Drop repeats: same URL, then headlines with token_set_ratio >= threshold.

    Of a duplicate pair the favorite-source / with-image / longer-summary one is kept.
    Headlines similar to `recent_titles` (earlier editions) are excluded.
    """
    kept: list[Candidate] = []
    for cand in cands:
        if any(
            fuzz.token_set_ratio(cand.title, old, score_cutoff=DEDUPE_THRESHOLD)
            for old in recent_titles
        ):
            continue
        for index, other in enumerate(kept):
            same_url = other.url_hash == cand.url_hash
            if same_url or fuzz.token_set_ratio(
                cand.title, other.title, score_cutoff=DEDUPE_THRESHOLD
            ):
                if _rank(cand) > _rank(other):
                    kept[index] = cand
                break
        else:
            kept.append(cand)
    return kept
