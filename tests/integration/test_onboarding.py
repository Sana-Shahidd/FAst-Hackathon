"""Onboarding through the real routes and the real test Supabase project."""

from __future__ import annotations

import html
import ipaddress
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.agents import runner
from app.models import ParsedInterest, ProfilerOut
from app.services import i18n, sources

pytestmark = pytest.mark.integration


async def names_are_public(host: str) -> bool:
    """Stand-in for DNS: host names count as public, IP literals are still judged for real."""
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
TOPICS = ["ai", "pakistan", "startups", "sports_cricket", "climate"]


def csrf_headers(client: TestClient) -> dict[str, str]:
    client.get("/login")  # makes sure the CSRF cookie exists
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def full_form(**overrides) -> dict:
    form = {
        "edition_lang": "ur",
        "source_langs": ["en"],
        "topics": TOPICS,
        "topic_level_ai": "3",
        "topic_level_pakistan": "1",
        "topic_level_startups": "2",
        "taste": json.dumps(
            [
                {"topic_key": "ai", "vote": "up"},
                {"topic_key": "pakistan", "vote": "down"},
                {"topic_key": "startups", "vote": "up"},
            ]
        ),
        "custom_interests": json.dumps(
            [{"label": "Pakistani startups", "query": '"Pakistan" startup'}]
        ),
        "favorite_sources": json.dumps(["bbc", "bbc_urdu"]),
        "custom_feeds": json.dumps([]),
        "muted_keywords": json.dumps(["Crypto", "celebrity gossip"]),
        "city": "Lahore",
        "timezone": "Asia/Karachi",
        "reading_minutes": "20",
        "notify": "1",
    }
    form.update(overrides)
    return form


# ------------------------------------------------------------------ pages


def test_onboarding_requires_login(client: TestClient) -> None:
    for path in ("/onboarding", "/onboarding/step/1", "/onboarding/taste?topics=ai"):
        response = client.get(path, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (
            303,
            "/login",
        ), path
    post = client.post("/onboarding", data={}, follow_redirects=False)
    assert post.status_code == 403  # no CSRF cookie either


def test_page_has_five_steps_24_topics_and_language_tiles(
    client: TestClient, user
) -> None:
    html = client.get("/onboarding").text
    assert html.count('class="ob-step"') == 5
    assert html.count('name="topics"') == 24
    for name in (
        "edition_lang",
        "source_langs",
        "custom_interests",
        "favorite_sources",
        "taste",
        "muted_keywords",
        "city",
        "timezone",
    ):
        assert f'name="{name}"' in html, name
    for info in i18n.languages().values():
        assert info["native"] in html
    assert i18n.t("ob.finish", "en") in html and "/static/onboarding.js" in html


def test_urdu_onboarding_is_rtl_and_offers_native_outlets_first(
    client: TestClient, user
) -> None:
    html = client.get("/onboarding?lang=ur").text
    assert 'dir="rtl"' in html and i18n.t("ob.topics.title", "ur") in html
    assert html.index('data-key="bbc_urdu"') < html.index('data-key="bbc"')
    assert i18n.t("topic.ai", "ur") in html


@pytest.mark.parametrize(
    ("n", "title_key"),
    [
        (1, "ob.lang.title"),
        (2, "ob.topics.title"),
        (3, "ob.custom.title"),
        (4, "ob.taste.title"),
        (5, "ob.morning.title"),
    ],
)
def test_each_step_is_available_as_a_fragment_in_the_chosen_language(
    client: TestClient, user, n: int, title_key: str
) -> None:
    response = client.get(f"/onboarding/step/{n}?lang=ar")
    assert response.status_code == 200
    assert "<html" not in response.text  # a fragment, not a page
    assert i18n.t(title_key, "ar") in response.text


@pytest.mark.parametrize("n", [0, 6, 99])
def test_unknown_steps_are_404(client: TestClient, user, n: int) -> None:
    assert client.get(f"/onboarding/step/{n}").status_code == 404


# --------------------------------------------------------- Profiler fragment


def test_parse_uses_the_profiler_agent_and_shows_removable_chips(
    client: TestClient, user, monkeypatch
) -> None:
    async def fake(key, factory, input, edition_id, **_):
        assert key == "profiler"
        return ProfilerOut(
            interests=[
                ParsedInterest(label="Pakistani startups", query='"Pakistan" startup')
            ]
        )

    monkeypatch.setattr(runner, "run_agent", fake)
    response = client.post(
        "/onboarding/parse",
        data={"text": "startups in Pakistan"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    assert (
        'data-label="Pakistani startups"' in response.text and "chip-x" in response.text
    )


def test_parse_falls_back_to_splitting_when_the_agent_fails(
    client: TestClient, user, monkeypatch
) -> None:
    async def failing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner, "run_agent", failing)
    response = client.post(
        "/onboarding/parse",
        data={"text": "F1, cricket and climate"},
        headers=csrf_headers(client),
    )
    labels = re.findall(r'data-label="([^"]+)"', response.text)
    assert labels == ["F1", "cricket", "climate"]


def test_parse_escapes_whatever_the_agent_returns(
    client: TestClient, user, monkeypatch
) -> None:
    async def hostile(*_args, **_kwargs):
        return ProfilerOut(
            interests=[
                ParsedInterest(
                    label="<script>alert(1)</script>", query='"x" onmouseover="y"'
                )
            ]
        )

    monkeypatch.setattr(runner, "run_agent", hostile)
    response = client.post(
        "/onboarding/parse", data={"text": "x"}, headers=csrf_headers(client)
    )
    assert "<script>alert(1)</script>" not in response.text
    assert 'onmouseover="y"' not in response.text


def test_parse_needs_a_csrf_token(client: TestClient, user) -> None:
    assert client.post("/onboarding/parse", data={"text": "x"}).status_code == 403


# --------------------------------------------------------- pasted feeds


def test_pasted_feed_is_validated_and_shown_as_a_chip(
    client: TestClient, user, feeds_mock, monkeypatch
) -> None:
    monkeypatch.setattr(sources, "_is_public_host", names_are_public)
    feeds_mock.get("https://blog.example.com/feed.xml").respond(
        200, content=(FIXTURES / "custom_good.xml").read_bytes()
    )
    feeds_mock.get("https://site.example.com/").respond(
        200, content=(FIXTURES / "not_a_feed.html").read_bytes()
    )
    good = client.post(
        "/onboarding/feed",
        data={"url": "https://blog.example.com/feed.xml"},
        headers=csrf_headers(client),
    )
    assert (
        'data-url="https://blog.example.com/feed.xml"' in good.text
        and "My Favourite Blog" in good.text
    )
    bad = client.post(
        "/onboarding/feed",
        data={"url": "https://site.example.com/"},
        headers=csrf_headers(client),
    )
    assert (
        i18n.t("sources.invalid", "en") in html.unescape(bad.text)
        and "data-url" not in bad.text
    )
    private = client.post(
        "/onboarding/feed",
        data={"url": "http://127.0.0.1/rss"},
        headers=csrf_headers(client),
    )
    assert i18n.t("sources.invalid", "en") in html.unescape(private.text)


# ---------------------------------------------------------- taste test


def test_taste_test_shows_eight_real_headlines_spread_over_topics(
    client: TestClient, user, feeds_mock
) -> None:
    response = client.get("/onboarding/taste?topics=ai,pakistan,startups")
    cards = re.findall(r'class="taste-card" data-topic="([a-z_]+)"', response.text)
    assert len(cards) == 8  # 3 topics x 6 stories available, capped at 8
    assert cards[:3] == ["ai", "pakistan", "startups"]  # one per topic first
    assert cards[3:6] == ["ai", "pakistan", "startups"]
    assert (
        response.text.count("taste-btn") == 16
    )  # a thumbs-up and a thumbs-down on every card
    assert "Test Wire" in response.text


def test_taste_test_caps_at_eight_cards(client: TestClient, user, feeds_mock) -> None:
    topics = "ai,pakistan,startups,climate,science"
    cards = re.findall(
        r'class="taste-card"', client.get(f"/onboarding/taste?topics={topics}").text
    )
    assert len(cards) == 8


def test_taste_test_without_feeds_shows_a_friendly_message(
    client: TestClient, user, feeds_mock
) -> None:
    feeds_mock.get("https://news.google.com/rss/search").respond(500)
    response = client.get("/onboarding/taste?topics=ai,pakistan")
    assert "taste-card" not in response.text
    assert i18n.t("empty.thin", "en") in response.text


# ------------------------------------------------------------ saving


def rows(admin, table: str, user_id: str, columns: str = "*") -> list[dict]:
    return admin.table(table).select(columns).eq("user_id", user_id).execute().data


def test_full_onboarding_saves_profile_interests_favorites_and_mutes(
    client: TestClient, user, admin, post_form
) -> None:
    response = post_form(client, "/onboarding", **full_form())
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/paper/generate?first=1",
    )

    profile = rows(admin, "profiles", user.id)[0]
    assert profile["edition_lang"] == "ur" and profile["source_langs"] == ["en"]
    assert (
        profile["city"],
        profile["timezone"],
        profile["reading_minutes"],
        profile["notify"],
    ) == ("Lahore", "Asia/Karachi", 20, True)
    assert profile["onboarded_at"] is not None

    interests = {
        r["topic_key"] or r["label"]: r for r in rows(admin, "interests", user.id)
    }
    assert len(interests) == 6  # 5 topics + 1 custom
    assert interests["ai"]["weight"] == 1.0  # "obsessed" 1.0 + taste 0.15, clamped
    assert interests["pakistan"]["weight"] == 0.25  # "a little" 0.4 - 0.15
    assert interests["startups"]["weight"] == 0.85  # "a lot" 0.7 + 0.15
    assert interests["climate"]["weight"] == 0.7  # untouched
    assert interests["ai"]["label"] == i18n.t(
        "topic.ai", "ur"
    )  # stored in the edition language
    assert interests["Pakistani startups"]["source"] == "custom"
    assert interests["Pakistani startups"]["weight"] == 0.7

    history = (
        admin.table("interest_history")
        .select("old_weight,new_weight,reason,interest_id")
        .in_("interest_id", [r["id"] for r in interests.values()])
        .execute()
        .data
    )
    moves = sorted((h["old_weight"], h["new_weight"]) for h in history)
    # "ai" was already at the cap, so only the two topics that really moved are logged
    assert moves == [(0.4, 0.25), (0.7, 0.85)]
    assert {h["reason"] for h in history} == {"taste_test"}

    favorites = {r["feed_url"]: r for r in rows(admin, "favorite_sources", user.id)}
    assert {r["catalog_key"] for r in favorites.values()} == {"bbc", "bbc_urdu"}
    assert all(r["kind"] == "catalog" for r in favorites.values())
    mutes = {r["keyword"] for r in rows(admin, "muted_keywords", user.id)}
    assert mutes == {"crypto", "celebrity gossip"}  # lower-cased


def test_resubmitting_replaces_instead_of_duplicating(
    client: TestClient, user, admin, post_form
) -> None:
    post_form(client, "/onboarding", **full_form())
    second = post_form(
        client,
        "/onboarding",
        **full_form(topics=TOPICS[:3], muted_keywords=json.dumps(["spoilers"])),
    )
    assert second.status_code == 303
    assert len(rows(admin, "interests", user.id)) == 4  # 3 topics + 1 custom, not 10
    assert {r["keyword"] for r in rows(admin, "muted_keywords", user.id)} == {
        "spoilers"
    }
    assert len(rows(admin, "favorite_sources", user.id)) == 2


def test_a_pasted_feed_that_validates_is_saved_as_a_custom_favorite(
    client: TestClient, user, admin, post_form, feeds_mock, monkeypatch
) -> None:
    monkeypatch.setattr(sources, "_is_public_host", names_are_public)
    feeds_mock.get("https://blog.example.com/feed.xml").respond(
        200, content=(FIXTURES / "custom_good.xml").read_bytes()
    )
    feeds_mock.get("https://dead.example.com/rss").respond(404)
    form = full_form(
        favorite_sources=json.dumps(["bbc"]),
        custom_feeds=json.dumps(
            ["https://blog.example.com/feed.xml", "https://dead.example.com/rss"]
        ),
    )
    assert post_form(client, "/onboarding", **form).status_code == 303
    favorites = rows(admin, "favorite_sources", user.id)
    custom = [r for r in favorites if r["kind"] == "custom"]
    assert [(r["feed_url"], r["name"], r["catalog_key"]) for r in custom] == [
        ("https://blog.example.com/feed.xml", "My Favourite Blog", None)
    ]
    assert len(favorites) == 2  # bbc + the one valid custom feed


def test_fewer_than_three_topics_is_rejected_and_saves_nothing(
    client: TestClient, user, admin, post_form
) -> None:
    response = post_form(client, "/onboarding", **full_form(topics=["ai", "pakistan"]))
    assert response.status_code == 400
    assert i18n.t("ob.topics.min", "ur") in response.text
    assert rows(admin, "profiles", user.id)[0]["onboarded_at"] is None
    assert rows(admin, "interests", user.id) == []


def test_posting_without_csrf_is_forbidden_and_saves_nothing(
    client: TestClient, user, admin
) -> None:
    assert (
        client.post("/onboarding", data=full_form(), follow_redirects=False).status_code
        == 403
    )
    assert rows(admin, "interests", user.id) == []


def test_after_onboarding_login_goes_straight_to_todays_paper(
    make_user, post_form, admin
) -> None:
    from app.main import app

    browser = TestClient(app)
    reader = make_user()
    assert (
        post_form(
            browser, "/login", email=reader.email, password=reader.password
        ).headers["location"]
        == "/onboarding"
    )
    assert post_form(browser, "/onboarding", **full_form()).status_code == 303
    again = TestClient(app)
    assert (
        post_form(
            again, "/login", email=reader.email, password=reader.password
        ).headers["location"]
        == "/paper/today"
    )


def test_one_readers_onboarding_never_touches_another_readers_rows(
    make_user, post_form, admin
) -> None:
    from app.main import app

    a, b = make_user("A"), make_user("B")
    ca = TestClient(app)
    post_form(ca, "/login", email=a.email, password=a.password)
    post_form(ca, "/onboarding", **full_form())
    assert len(rows(admin, "interests", a.id)) == 6
    assert rows(admin, "interests", b.id) == []
    assert rows(admin, "favorite_sources", b.id) == []
    assert rows(admin, "profiles", b.id)[0]["onboarded_at"] is None
