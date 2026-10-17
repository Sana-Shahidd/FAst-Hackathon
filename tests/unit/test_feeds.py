"""Feed URLs, fixture normalisation, HTML stripping, dedupe, fetching (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import feedparser
import httpx
import pytest
import respx

from app.config import MAX_FEED_URLS, SUPPORTED_LANGS
from app.models import Candidate, FavoriteSource, FeedUrl, Interest, Profile
from app.services import feeds, i18n

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
NOW = datetime(2026, 10, 17, 6, 0, tzinfo=UTC)


def parse_fixture(fixture: str, **feed_kwargs) -> list[Candidate]:
    parsed = feedparser.parse((FIXTURES / fixture).read_bytes())
    feed = FeedUrl(
        url="https://example.com/feed", lang="en", kind="topic", **feed_kwargs
    )
    return feeds.normalise(parsed, feed)


def cand(title: str, url: str | None = None, **kw) -> Candidate:
    return Candidate(
        url=url or f"https://example.com/{abs(hash(title))}", title=title, **kw
    )


# ------------------------------------------------------------------ URL building


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_google_news_url_uses_the_edition_hl_gl_ceid(lang: str) -> None:
    url = feeds.google_news_url('"AI" OR robots', lang)
    parts = urlparse(url)
    query = parse_qs(parts.query)
    gn = i18n.languages()[lang]["gn"]
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https",
        "news.google.com",
        "/rss/search",
    )
    assert query["q"] == ['"AI" OR robots']
    assert (query["hl"], query["gl"], query["ceid"]) == (
        [gn["hl"]],
        [gn["gl"]],
        [gn["ceid"]],
    )


def test_topic_query_prefers_local_text_then_english() -> None:
    assert feeds.topic_query("ai", "ur") == feeds.topics()["ai"]["query_local"]["ur"]
    assert feeds.topic_query("ai", "en") == feeds.topics()["ai"]["query"]
    key, lang = next(
        (k, lang)
        for k, t in feeds.topics().items()
        for lang in SUPPORTED_LANGS
        if lang != "en" and lang not in t.get("query_local", {})
    )
    assert feeds.topic_query(key, lang) == feeds.topics()[key]["query"]


def make_interests() -> list[Interest]:
    return [
        Interest(
            id="1", label="Pakistan", topic_key="pakistan", query="Pakistan", weight=0.5
        ),
        Interest(id="2", label="AI", topic_key="ai", query="ai", weight=0.9),
        Interest(
            id="3", label="F1 tyres", query='"F1" tyres', weight=0.7, source="custom"
        ),
        Interest(
            id="4",
            label="Hidden",
            topic_key="space",
            query="space",
            weight=1.0,
            active=False,
        ),
    ]


def test_build_feed_urls_orders_favorites_then_interests_by_weight() -> None:
    favs = [
        FavoriteSource(
            catalog_key="bbc", name="BBC News", feed_url="https://bbc.example/rss"
        ),
        FavoriteSource(name="Blog", feed_url="https://blog.example/rss", kind="custom"),
    ]
    out = feeds.build_feed_urls(
        Profile(edition_lang="en", city="Lahore"), make_interests(), favs
    )
    assert [f.kind for f in out[:2]] == ["favorite", "custom"]
    assert all(f.favorite for f in out[:2])
    labels = [f.name for f in out if f.kind in ("topic", "interest")]
    assert labels == ["AI", "F1 tyres", "Pakistan"]  # by weight; inactive skipped
    city = next(f for f in out if f.kind == "city")
    assert parse_qs(urlparse(city.url).query)["q"] == ['"Lahore"']
    assert city.topic_key == "your_city"
    assert any(f.kind == "curated" for f in out)
    assert len({f.url for f in out}) == len(out)


def test_build_feed_urls_uses_local_queries_and_adds_source_languages() -> None:
    profile = Profile(edition_lang="ur", source_langs=["en"])
    out = feeds.build_feed_urls(profile, make_interests())
    ai_ur = next(f for f in out if f.name == "AI" and f.lang == "ur")
    assert parse_qs(urlparse(ai_ur.url).query)["q"] == [
        feeds.topics()["ai"]["query_local"]["ur"]
    ]
    assert any(f.lang == "en" and f.name == "AI" for f in out)
    assert {f.name for f in out if f.kind == "curated" and f.lang == "ur"} >= {
        "Express Urdu"
    }


def test_build_feed_urls_is_capped() -> None:
    many = [
        Interest(id=str(n), label=f"topic {n}", query=f"topic {n}", weight=0.5)
        for n in range(40)
    ]
    out = feeds.build_feed_urls(
        Profile(edition_lang="en", source_langs=["ur", "hi"]), many
    )
    assert len(out) == MAX_FEED_URLS


def test_english_fallback_urls_use_the_english_edition() -> None:
    out = feeds.english_fallback_urls(make_interests())
    assert [f.lang for f in out] == ["en"] * 3
    assert "hl=en-US" in out[0].url


# ----------------------------------------------------------------- normalisation


def test_google_news_fixture_is_normalised() -> None:
    items = parse_fixture("google_news_en.xml", topic_key="ai", interest_id="i-9")
    assert len(items) == 5  # the javascript: link is dropped
    first = items[0]
    assert first.title == "OpenAI launches new reasoning model for developers"
    assert first.source_name == "Reuters"
    assert first.summary == ""  # Google News only repeats the headline and source
    assert first.published_at == datetime(2026, 10, 17, 5, 0, tzinfo=UTC)
    assert (first.topic_key, first.interest_id, first.lang) == ("ai", "i-9", "en")
    assert first.favorite is False


def test_html_is_stripped_and_images_found() -> None:
    urdu, cricket = parse_fixture("bbc_urdu.xml", name="BBC Urdu")
    assert (
        urdu.summary == "حکومت نے نئی پالیسی کا اعلان کیا ہے۔"
    )  # tags and <script> gone
    assert urdu.image_url == "https://ichef.bbci.co.uk/news/240/c1.jpg"
    assert cricket.image_url == "https://ichef.bbci.co.uk/news/640/c2.png"
    assert cricket.title == "Cricket: Pakistan beat Australia & take series lead"
    assert urdu.source_name == "BBC Urdu"


def test_strip_html_and_summary_limit() -> None:
    assert (
        feeds.strip_html("<p>Hello&nbsp;<b>world</b> &amp; all</p>")
        == "Hello world & all"
    )
    assert feeds.strip_html("a<script>evil()</script><style>x{}</style>b") == "a b"
    long_text = " ".join(["word"] * 400)
    parsed = feedparser.parse(
        f"<rss version='2.0'><channel><title>t</title><item><title>T</title>"
        f"<link>https://x.example/a</link><description>{long_text}</description></item>"
        f"</channel></rss>"
    )
    item = feeds.normalise(parsed, FeedUrl(url="u", lang="en", kind="curated"))[0]
    assert len(item.summary) <= 600
    assert item.summary.endswith("…")


@pytest.mark.parametrize(
    ("text", "requested", "expected"),
    [
        ("پاکستان میں نئی ٹیکنالوجی", "ur", "ur"),
        ("پاکستان میں نئی ٹیکنالوجی", "en", "ur"),  # Urdu-only letters
        ("الذكاء الاصطناعي يغير العالم", "ar", "ar"),
        ("الذكاء الاصطناعي يغير العالم", "en", "ar"),
        ("Pakistan wins the series", "ur", "en"),  # Google News has no Urdu edition
        ("Pakistan wins the series", "en", "en"),
        ("El equipo gana la serie", "es", "es"),
        ("पाकिस्तान ने सीरीज़ जीती", "hi", "hi"),
        ("বাংলাদেশ সিরিজ জিতেছে", "bn", "bn"),
        ("人工智能改变世界", "zh", "zh"),
        ("1234 !!!", "fr", "fr"),  # no letters: keep the requested Latin language
        ("1234 !!!", "ur", "en"),
    ],
)
def test_detect_lang_from_script(text: str, requested: str, expected: str) -> None:
    assert feeds.detect_lang(text, requested) == expected


def test_curated_feeds_cover_every_language() -> None:
    assert set(feeds.curated()) == set(SUPPORTED_LANGS)
    for lang, entries in feeds.curated().items():
        assert 2 <= len(entries) <= 4, lang
        for entry in entries:
            assert entry["url"].startswith("https://")
            assert entry["name"] and entry["topic_key"] == "world"


def test_every_topic_has_a_query_and_valid_local_languages() -> None:
    assert len(feeds.topics()) == 24
    for key, topic in feeds.topics().items():
        assert topic["query"], key
        assert set(topic.get("query_local", {})) <= set(SUPPORTED_LANGS), key


# ------------------------------------------------------------------------ fresh


def test_filter_fresh_keeps_recent_dated_items_only() -> None:
    items = parse_fixture("google_news_en.xml")
    fresh = feeds.filter_fresh(items, 36, now=NOW)
    assert {c.source_name for c in fresh} == {"Reuters", "The Verge", "Dawn"}
    assert len(feeds.filter_fresh(items, 72, now=NOW)) == len(fresh)
    assert feeds.filter_fresh([cand("Undated")], 72, now=NOW) == []


# ------------------------------------------------------------------------ dedupe


def test_dedupe_removes_same_url_and_near_duplicate_headlines() -> None:
    items = feeds.filter_fresh(parse_fixture("google_news_en.xml"), 36, now=NOW)
    out = feeds.dedupe(items, [])
    assert [c.source_name for c in out] == ["Reuters", "Dawn"]


def test_dedupe_keeps_the_candidate_with_image_or_longer_summary() -> None:
    plain = cand(
        "Central bank raises interest rates again",
        "https://a.example/1",
        summary="Short",
    )
    pic = cand(
        "Central bank raises interest rates again today",
        "https://b.example/2",
        image_url="https://i/x.jpg",
    )
    assert feeds.dedupe([plain, pic], []) == [pic]
    longer = cand(
        "Central bank raises interest rates again",
        "https://c.example/3",
        summary="Longer text",
    )
    assert feeds.dedupe([plain, longer], []) == [longer]


def test_dedupe_prefers_a_favorite_source_story() -> None:
    other = cand(
        "Floods hit northern Pakistan overnight",
        "https://a.example/1",
        image_url="https://i/x.jpg",
    )
    fav = cand(
        "Floods hit northern Pakistan overnight", "https://b.example/2", favorite=True
    )
    assert feeds.dedupe([other, fav], []) == [fav]


def test_dedupe_keeps_different_stories_and_drops_recent_titles() -> None:
    a = cand("Stock markets rally as inflation cools")
    b = cand("Electric vehicle sales double in a year")
    assert feeds.dedupe([a, b], []) == [a, b]
    seen = ["Stock markets rally as inflation cools sharply"]
    assert feeds.dedupe([a, b], seen) == [b]


# ----------------------------------------------------------------------- fetching


@respx.mock
async def test_fetch_all_runs_in_parallel_and_skips_failing_feeds() -> None:
    xml = (FIXTURES / "google_news_en.xml").read_bytes()
    respx.get("https://good.example/rss").respond(200, content=xml)
    respx.get("https://broken.example/rss").respond(500)
    respx.get("https://slow.example/rss").mock(side_effect=httpx.ConnectTimeout("slow"))
    urls = [
        FeedUrl(
            url="https://good.example/rss", lang="en", kind="topic", topic_key="ai"
        ),
        FeedUrl(url="https://broken.example/rss", lang="en", kind="topic"),
        FeedUrl(url="https://slow.example/rss", lang="en", kind="topic"),
    ]
    cands, ok, failed = await feeds.fetch_all_with_stats(urls)
    assert (ok, failed) == (1, 2)
    assert len(cands) == 5
    assert {c.topic_key for c in cands} == {"ai"}
    assert len(await feeds.fetch_all(urls)) == 5
