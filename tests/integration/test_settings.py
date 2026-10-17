"""Settings, mutes, favorite sources and the scheduler through the real routes (T-12: F-06, F-18, F-20, F-23)."""

from __future__ import annotations

import asyncio
import html as htmllib
import ipaddress
from datetime import datetime, time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import deps, jobs
from app.agents import runner
from app.main import app
from app.services import edition as pipeline
from app.services import i18n, sources

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/login")
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def profile(admin, user_id: str) -> dict:
    return admin.table("profiles").select("*").eq("user_id", user_id).execute().data[0]


def mutes(admin, user_id: str) -> set[str]:
    rows = (
        admin.table("muted_keywords")
        .select("keyword")
        .eq("user_id", user_id)
        .execute()
        .data
    )
    return {r["keyword"] for r in rows}


def favorites(admin, user_id: str) -> list[dict]:
    return (
        admin.table("favorite_sources")
        .select("*")
        .eq("user_id", user_id)
        .execute()
        .data
    )


def form(client: TestClient, **fields) -> dict:
    page = client.get("/settings").text
    token = page.split('name="csrf_token" value="')[1].split('"')[0]
    base = {
        "csrf_token": token,
        "display_name": "Sana",
        "edition_lang": "en",
        "city": "Lahore",
        "timezone": "Asia/Karachi",
        "reading_minutes": "10",
        "delivery_time": "06:00",
    }
    return {**base, **fields}


# ----------------------------------------------------------------- settings


def test_the_settings_page_shows_every_control_with_the_current_values(
    client: TestClient, onboarded_user, admin
) -> None:
    page = client.get("/settings")
    assert page.status_code == 200
    text = page.text
    for name in (
        "display_name",
        "edition_lang",
        "city",
        "timezone",
        "reading_minutes",
        "delivery_time",
        "notify",
    ):
        assert f'name="{name}"' in text, name
    assert (
        'value="Asia/Karachi"' in text
        and 'value="Lahore"' in text
        and 'value="06:00"' in text
    )
    for info in i18n.languages().values():
        assert info["native"] in text
    assert 'action="/settings/comfort"' in text or 'hx-post="/settings/comfort"' in text
    assert (
        'action="/logout"' in text and 'id="mutes"' in text and 'id="sources"' in text
    )


def test_saving_settings_updates_the_profile_and_confirms(
    client: TestClient, onboarded_user, admin
) -> None:
    data = form(
        client,
        display_name="Sana Shahid",
        edition_lang="ur",
        city="Karachi",
        reading_minutes="20",
        delivery_time="05:15",
        notify="1",
    )
    response = client.post("/settings", data=data, follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/settings?saved=1",
    )
    saved = profile(admin, onboarded_user.id)
    assert (saved["display_name"], saved["edition_lang"], saved["city"]) == (
        "Sana Shahid",
        "ur",
        "Karachi",
    )
    assert (
        saved["reading_minutes"],
        str(saved["delivery_time"])[:5],
        saved["notify"],
    ) == (20, "05:15", True)
    after = client.get("/settings?saved=1")
    assert htmllib.unescape(i18n.t("settings.saved", "ur")) in htmllib.unescape(
        after.text
    )
    assert 'dir="rtl"' in after.text  # the page follows the new edition language


@pytest.mark.parametrize(
    "bad",
    [
        {"timezone": "Mars/Olympus"},
        {"reading_minutes": "7"},
        {"delivery_time": "late"},
        {"edition_lang": "xx"},
    ],
)
def test_invalid_settings_are_rejected_and_nothing_changes(
    client: TestClient, onboarded_user, admin, bad: dict
) -> None:
    before = profile(admin, onboarded_user.id)
    response = client.post(
        "/settings", data=form(client, **bad), follow_redirects=False
    )
    assert response.status_code == 400 and 'role="alert"' in response.text
    after = profile(admin, onboarded_user.id)
    assert (after["timezone"], after["reading_minutes"], after["edition_lang"]) == (
        before["timezone"],
        before["reading_minutes"],
        before["edition_lang"],
    )


def test_settings_need_csrf_a_login_and_onboarding(
    client: TestClient, onboarded_user, make_user, post_form
) -> None:
    assert client.post("/settings", data={"display_name": "x"}).status_code == 403
    anonymous = TestClient(app).get("/settings", follow_redirects=False)
    assert (anonymous.status_code, anonymous.headers["location"]) == (303, "/login")
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    assert (
        browser.get("/settings", follow_redirects=False).headers["location"]
        == "/onboarding"
    )


# -------------------------------------------------------------------- mutes


def test_mute_words_can_be_added_and_removed_in_place(
    client: TestClient, onboarded_user, admin
) -> None:
    assert mutes(admin, onboarded_user.id) == {"cricket"}  # from onboarding
    added = client.post(
        "/mutes",
        data={"action": "add", "keyword": "  Celebrity Gossip "},
        headers=csrf(client),
    )
    assert (
        added.status_code == 200
        and "<html" not in added.text
        and 'id="mutes"' in added.text
    )
    assert "celebrity gossip" in added.text
    assert mutes(admin, onboarded_user.id) == {"cricket", "celebrity gossip"}
    client.post(
        "/mutes",
        data={"action": "add", "keyword": "celebrity gossip"},
        headers=csrf(client),
    )  # again
    assert len(mutes(admin, onboarded_user.id)) == 2
    removed = client.post(
        "/mutes", data={"action": "remove", "keyword": "cricket"}, headers=csrf(client)
    )
    assert "cricket" not in removed.text
    assert mutes(admin, onboarded_user.id) == {"celebrity gossip"}


def test_bad_mute_words_and_the_limit_are_refused_with_a_message(
    client: TestClient, onboarded_user, admin
) -> None:
    short = client.post(
        "/mutes", data={"action": "add", "keyword": "x"}, headers=csrf(client)
    )
    assert i18n.t("settings.mute_length", "en") in short.text
    admin.table("muted_keywords").delete().eq("user_id", onboarded_user.id).execute()
    admin.table("muted_keywords").insert(
        [{"user_id": onboarded_user.id, "keyword": f"word{i:02d}"} for i in range(30)]
    ).execute()
    over = client.post(
        "/mutes", data={"action": "add", "keyword": "one more"}, headers=csrf(client)
    )
    assert i18n.t("settings.mute_limit", "en") in over.text
    assert len(mutes(admin, onboarded_user.id)) == 30
    assert (
        client.post(
            "/mutes", data={"action": "explode"}, headers=csrf(client)
        ).status_code
        == 422
    )


def test_muting_a_word_removes_matching_stories_from_the_next_paper(
    client: TestClient, onboarded_user, admin, feeds_mock, fake_agents, monkeypatch
) -> None:
    import httpx

    from tests.conftest import rss

    def search(request: httpx.Request) -> httpx.Response:
        titles = ["Zebra stampede in the city"] + [
            f"story {i} " + "x" * i for i in range(5)
        ]
        return httpx.Response(200, text=rss(titles, "Wire"))

    feeds_mock.get("https://news.google.com/rss/search").mock(side_effect=search)
    client.post(
        "/mutes", data={"action": "add", "keyword": "zebra"}, headers=csrf(client)
    )
    monkeypatch.setattr(runner, "run_agent", fake_agents)
    day = pipeline.local_date_for(profile(admin, onboarded_user.id)["timezone"])
    edition_id = asyncio.run(pipeline.generate_edition(onboarded_user.id, day))
    headlines = [
        a["headline"]
        for a in admin.table("edition_articles")
        .select("headline")
        .eq("edition_id", edition_id)
        .execute()
        .data
    ]
    assert not any("zebra" in h.lower() for h in headlines) and headlines


def test_mutes_are_private(
    client: TestClient, onboarded_user, admin, make_user, post_form
) -> None:
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    browser.post(
        "/mutes", data={"action": "remove", "keyword": "cricket"}, headers=csrf(browser)
    )
    assert mutes(admin, onboarded_user.id) == {"cricket"}
    assert (
        client.post("/mutes", data={"action": "add", "keyword": "ok word"}).status_code
        == 403
    )


# ------------------------------------------------------------------ sources


def test_a_catalog_outlet_can_be_added_and_removed(
    client: TestClient, onboarded_user, admin
) -> None:
    before = {f["catalog_key"] for f in favorites(admin, onboarded_user.id)}
    assert before == {"bbc"}
    dawn = next(o for o in sources.catalog_for("en") if o["key"] not in before)
    added = client.post(
        "/sources",
        data={"action": "add_catalog", "catalog_key": dawn["key"]},
        headers=csrf(client),
    )
    assert added.status_code == 200 and dawn["name"] in htmllib.unescape(added.text)
    rows = favorites(admin, onboarded_user.id)
    assert {r["catalog_key"] for r in rows} == {"bbc", dawn["key"]}
    victim = next(r for r in rows if r["catalog_key"] == dawn["key"])
    client.post(
        "/sources", data={"action": "remove", "id": victim["id"]}, headers=csrf(client)
    )
    assert {r["catalog_key"] for r in favorites(admin, onboarded_user.id)} == {"bbc"}


def test_a_pasted_feed_is_validated_before_it_is_saved(
    client: TestClient, onboarded_user, admin, feeds_mock, monkeypatch
) -> None:
    async def public(host: str) -> bool:
        """Host names count as public (no DNS in tests); IP literals are still judged for real."""
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True

    monkeypatch.setattr(sources, "_is_public_host", public)
    feeds_mock.get("https://blog.example.com/feed.xml").respond(
        200, content=(FIXTURES / "custom_good.xml").read_bytes()
    )
    feeds_mock.get("https://site.example.com/").respond(
        200, content=(FIXTURES / "not_a_feed.html").read_bytes()
    )
    ok = client.post(
        "/sources",
        data={"action": "add_custom", "feed_url": "https://blog.example.com/feed.xml"},
        headers=csrf(client),
    )
    assert "My Favourite Blog" in ok.text
    custom = [f for f in favorites(admin, onboarded_user.id) if f["kind"] == "custom"]
    assert [(c["name"], c["feed_url"]) for c in custom] == [
        ("My Favourite Blog", "https://blog.example.com/feed.xml")
    ]
    bad = client.post(
        "/sources",
        data={"action": "add_custom", "feed_url": "https://site.example.com/"},
        headers=csrf(client),
    )
    assert htmllib.unescape(i18n.t("sources.invalid", "en")) in htmllib.unescape(
        bad.text
    )
    private = client.post(
        "/sources",
        data={"action": "add_custom", "feed_url": "http://127.0.0.1/rss"},
        headers=csrf(client),
    )
    assert (
        len([f for f in favorites(admin, onboarded_user.id) if f["kind"] == "custom"])
        == 1
    )
    assert private.status_code == 200


def test_sources_reject_unknown_outlets_and_strangers_cannot_remove_yours(
    client: TestClient, onboarded_user, admin, make_user, post_form
) -> None:
    refused = client.post(
        "/sources",
        data={"action": "add_catalog", "catalog_key": "no-such-outlet"},
        headers=csrf(client),
    )
    assert i18n.t("sources.invalid", "en") in htmllib.unescape(refused.text)
    mine = favorites(admin, onboarded_user.id)[0]
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    browser.post(
        "/sources", data={"action": "remove", "id": mine["id"]}, headers=csrf(browser)
    )
    assert len(favorites(admin, onboarded_user.id)) == 1
    assert (
        client.post(
            "/sources", data={"action": "explode"}, headers=csrf(client)
        ).status_code
        == 422
    )
    assert (
        client.get("/sources", follow_redirects=False).headers["location"]
        == "/settings#sources-card"
    )


# ---------------------------------------------------------------- scheduler


def test_the_scheduler_prints_due_papers_once_and_skips_early_ones(
    onboarded_user, admin, feeds_mock, fake_agents, monkeypatch
) -> None:
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(runner, "run_agent", fake_agents)
    zone = profile(admin, onboarded_user.id)["timezone"]
    day = pipeline.local_date_for(zone)
    at = lambda hour: datetime.combine(day, time(hour, 5), tzinfo=ZoneInfo(zone))
    mine = {onboarded_user.id}  # never touch other readers of the shared test database
    admin.table("profiles").update({"delivery_time": "06:00"}).eq(
        "user_id", onboarded_user.id
    ).execute()

    assert (
        asyncio.run(jobs.run_due_editions(at(0), mine)) == 0
    )  # 00:05 local: too early
    assert asyncio.run(pipeline.latest_edition(onboarded_user.id, day)) is None

    async def run_and_wait(moment):
        started = await jobs.run_due_editions(moment, mine)
        task = pipeline._running.get(onboarded_user.id)
        if task:
            await task
        return started

    assert asyncio.run(run_and_wait(at(7))) == 1  # 07:05 local: due
    ready = asyncio.run(pipeline.ready_edition(onboarded_user.id, day))
    assert ready is not None and ready["status"] == "ready"
    assert (
        asyncio.run(jobs.run_due_editions(at(8), mine)) == 0
    )  # already printed: never twice
