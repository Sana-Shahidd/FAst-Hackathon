"""Archive, Saved tab, regenerate and dev time travel through the real routes (T-09: F-09, F-19)."""

from __future__ import annotations

import asyncio
import html
import re
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.config import settings
from app.main import app
from app.services import edition as pipeline
from app.services import i18n

pytestmark = pytest.mark.integration


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/login")
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def print_day(user_id: str, day: date, *, regenerate: bool = False) -> str:
    return asyncio.run(pipeline.generate_edition(user_id, day, regenerate=regenerate))


def wait_for_redirect(client: TestClient, url: str, timeout: int = 150) -> str:
    """Poll a printing-status URL like the page does, until it says where the paper is."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(url)
        if target := response.headers.get("HX-Redirect"):
            return target
        time.sleep(1)
    raise AssertionError(f"{url} never finished printing")


def stories(admin, edition_id: str) -> list[dict]:
    return (
        admin.table("edition_articles")
        .select("id,headline,slot")
        .eq("edition_id", edition_id)
        .order("position")
        .execute()
        .data
    )


def day_of(edition: dict) -> date:
    return date.fromisoformat(edition["day"])


# ------------------------------------------------------------------ archive


def test_archive_lists_every_edition_newest_first_with_read_and_pdf(
    client: TestClient, edition, onboarded_user
) -> None:
    today = day_of(edition)
    yesterday, tomorrow = today - timedelta(days=1), today + timedelta(days=1)
    print_day(onboarded_user.id, yesterday)
    print_day(onboarded_user.id, tomorrow)
    page = client.get("/archive")
    assert page.status_code == 200
    html = page.text
    assert i18n.t("archive.title", "en") in html
    positions = [
        html.index(f'href="/paper/{d.isoformat()}"')
        for d in (tomorrow, today, yesterday)
    ]
    assert positions == sorted(positions)  # newest date first
    for d in (yesterday, today, tomorrow):
        assert f'href="/paper/{d.isoformat()}/pdf"' in html
        assert i18n.full_date(d, "en") in html
    assert html.count("Test lead headline") == 3
    for number in (1, 2, 3):
        assert i18n.t("paper.no", "en", n=number) in html
    assert client.get(f"/paper/{yesterday.isoformat()}").status_code == 200


def test_regenerating_keeps_the_old_version_reachable_by_version(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    day = day_of(edition)
    admin.table("editions").update({"lead_headline": "Old front page"}).eq(
        "id", edition["id"]
    ).execute()
    print_day(onboarded_user.id, day, regenerate=True)

    html = client.get("/archive").text
    assert 'class="mini-older"' in html and f'href="/paper/{day}?v=1"' in html
    assert i18n.t("archive.version", "en", n=1) in html
    assert html.count(f'href="/paper/{day}"') == 1  # one card per date, not per version

    old = client.get(f"/paper/{day}?v=1")
    assert old.status_code == 200 and "Old front page" in old.text
    assert f"/paper/{day}/print?v=1" in old.text and f"/paper/{day}/pdf?v=1" in old.text
    assert i18n.t("paper.regenerate", "en") not in old.text  # only the current version
    latest = client.get(f"/paper/{day}")
    assert "Old front page" not in latest.text and "Test lead headline" in latest.text
    assert client.get(f"/paper/{day}?v=99").status_code == 404
    assert client.get(f"/paper/{day}/print?v=1").status_code == 200


def test_archive_needs_a_login_and_onboarding(
    client: TestClient, edition, make_user, post_form
) -> None:
    anonymous = TestClient(app).get("/archive", follow_redirects=False)
    assert (anonymous.status_code, anonymous.headers["location"]) == (303, "/login")
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    response = browser.get("/archive", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/onboarding")


def test_an_empty_archive_says_so(client: TestClient, onboarded_user) -> None:
    assert i18n.t("archive.empty", "en") in client.get("/archive").text


# -------------------------------------------------------------------- saved


def test_saved_tab_groups_stories_by_date_and_unsaves_in_place(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    today = day_of(edition)
    yesterday = today - timedelta(days=1)
    old_id = print_day(onboarded_user.id, yesterday)
    today_stories = [s for s in stories(admin, edition["id"]) if s["slot"] != "lead"]
    old_story = stories(admin, old_id)[1]
    for story in (old_story, today_stories[0], today_stories[1]):
        assert (
            client.post(f"/saved/{story['id']}", headers=csrf(client)).status_code
            == 200
        )

    page = client.get("/saved")
    assert page.status_code == 200
    html = page.text
    assert html.index(i18n.full_date(today, "en")) < html.index(
        i18n.full_date(yesterday, "en")
    )
    for story in (old_story, today_stories[0], today_stories[1]):
        assert f'href="/r/{story["id"]}"' in html and story["headline"] in html

    fragment = client.post(
        f"/saved/{today_stories[0]['id']}", data={"ctx": "saved"}, headers=csrf(client)
    )
    assert 'id="saved-list"' in fragment.text and "<html" not in fragment.text
    assert f'href="/r/{today_stories[0]["id"]}"' not in fragment.text
    assert f'href="/r/{today_stories[1]["id"]}"' in fragment.text

    for story in (today_stories[1], old_story):
        client.post(
            f"/saved/{story['id']}", data={"ctx": "saved"}, headers=csrf(client)
        )
    assert i18n.t("saved.empty", "en") in client.get("/saved").text


def test_saved_stories_survive_a_regenerated_edition(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    story = next(s for s in stories(admin, edition["id"]) if s["slot"] != "lead")
    client.post(f"/saved/{story['id']}", headers=csrf(client))
    print_day(onboarded_user.id, day_of(edition), regenerate=True)
    assert f'href="/r/{story["id"]}"' in client.get("/saved").text


def test_the_saved_tab_is_private(
    client: TestClient, edition, admin, make_user, post_form, onboarded_user
) -> None:
    story = next(s for s in stories(admin, edition["id"]) if s["slot"] != "lead")
    client.post(f"/saved/{story['id']}", headers=csrf(client))
    anonymous = TestClient(app).get("/saved", follow_redirects=False)
    assert (anonymous.status_code, anonymous.headers["location"]) == (303, "/login")
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    assert (
        browser.get("/saved", follow_redirects=False).headers["location"]
        == "/onboarding"
    )
    tried = browser.post(
        f"/saved/{story['id']}", data={"ctx": "saved"}, headers=csrf(browser)
    )
    assert tried.status_code == 404
    assert (
        len(admin.table("saved_articles").select("*").execute().data) >= 1
    )  # still saved


# --------------------------------------------------------------- regenerate


def test_regenerate_prints_version_two_and_the_printing_page_waits_for_it(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    home = client.get("/paper/today").text
    assert 'action="/paper/generate"' in home and 'name="regenerate" value="1"' in home
    response = client.post(
        "/paper/generate",
        data={"regenerate": "1"},
        headers=csrf(client),
        follow_redirects=False,
    )
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/paper/generate",
    )
    waiting = client.get("/paper/generate", follow_redirects=False)
    assert (
        waiting.status_code == 200 and "steps" in waiting.text
    )  # NOT bounced back to the paper
    assert "step-working" in client.get("/paper/status").text
    assert wait_for_redirect(client, "/paper/status") == "/paper/today"

    rows = {
        r["version"]: r["status"]
        for r in admin.table("editions")
        .select("version,status")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data
    }
    assert rows == {1: "superseded", 2: "ready"}
    assert client.get("/paper/generate", follow_redirects=False).status_code == 303


def test_regenerating_needs_csrf_and_is_rate_limited(
    client: TestClient, edition, monkeypatch
) -> None:
    assert client.post("/paper/generate", data={"regenerate": "1"}).status_code == 403

    async def never_prints(*_a, **_k):
        return "x"

    monkeypatch.setattr(pipeline, "generate_edition", never_prints)
    codes = [
        client.post(
            "/paper/generate",
            data={"regenerate": "1"},
            headers=csrf(client),
            follow_redirects=False,
        ).status_code
        for _ in range(4)
    ]
    assert codes[:3] == [303, 303, 303] and codes[3] == 429


# -------------------------------------------------------------- time travel


def test_time_travel_prints_the_next_day_and_keeps_going(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    today = day_of(edition)
    assert i18n.t("dev.time_travel", "en") in html.unescape(
        client.get("/paper/today").text
    )
    first = client.post(
        "/dev/time-travel", headers=csrf(client), follow_redirects=False
    )
    tomorrow = today + timedelta(days=1)
    assert (first.status_code, first.headers["location"]) == (
        303,
        f"/paper/generate?day={tomorrow}",
    )
    assert (
        client.get(first.headers["location"], follow_redirects=False).status_code == 200
    )
    assert (
        wait_for_redirect(client, f"/paper/status?day={tomorrow}")
        == f"/paper/{tomorrow}"
    )
    assert client.get(f"/paper/{tomorrow}").status_code == 200
    assert f'href="/paper/{tomorrow}"' in client.get("/archive").text

    second = client.post(
        "/dev/time-travel", headers=csrf(client), follow_redirects=False
    )
    assert (
        second.headers["location"]
        == f"/paper/generate?day={tomorrow + timedelta(days=1)}"
    )


def test_time_travel_is_dev_only_and_needs_csrf_and_login(
    client: TestClient, edition, admin, onboarded_user, monkeypatch
) -> None:
    assert client.post("/dev/time-travel").status_code == 403
    anonymous = TestClient(app)
    response = anonymous.post(
        "/dev/time-travel", headers={**csrf(anonymous), "HX-Request": "true"}
    )
    assert response.status_code == 401
    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert client.post("/dev/time-travel", headers=csrf(client)).status_code == 404
    assert i18n.t("dev.time_travel", "en") not in html.unescape(
        client.get("/paper/today").text
    )
    ignored = client.get("/paper/generate?day=2099-01-01", follow_redirects=False)
    assert (
        ignored.status_code == 303
    )  # production ignores ?day= and shows today's paper
    editions = (
        admin.table("editions")
        .select("edition_date")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data
    )
    assert [e["edition_date"] for e in editions] == [
        edition["day"]
    ]  # nothing was printed


def test_the_status_url_survives_in_the_printing_page(
    client: TestClient, edition
) -> None:
    tomorrow = day_of(edition) + timedelta(days=1)
    client.post("/dev/time-travel", headers=csrf(client))
    page = client.get(f"/paper/generate?day={tomorrow}").text
    assert re.search(rf'hx-get="/paper/status\?day={tomorrow}"', page)
    wait_for_redirect(client, f"/paper/status?day={tomorrow}")
