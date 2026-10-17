"""The web edition and the article sheet through the real routes (T-07: F-07, F-22)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import i18n

pytestmark = pytest.mark.integration


def signals(admin, user_id: str, kind: str | None = None) -> list[dict]:
    query = admin.table("signals").select("*").eq("user_id", user_id)
    return (query.eq("kind", kind) if kind else query).execute().data


def other_reader(make_user, post_form) -> tuple[TestClient, object]:
    reader = make_user("Other")
    browser = TestClient(app)
    post_form(browser, "/login", email=reader.email, password=reader.password)
    return browser, reader


def test_edition_page_shows_hero_lead_sections_and_every_story(
    client: TestClient, edition
) -> None:
    page = client.get("/paper/today")
    assert page.status_code == 200
    html = page.text
    assert i18n.t("home.headlines", "en") in html
    assert "Test lead headline" in html and "Test dek line for the lead story." in html
    assert i18n.t("paper.no", "en", n=1) in html
    assert "Good morning, Test Reader!" in html  # the editor's note
    for line in ("Fact 1 from today", "Fact 3 from today"):
        assert line in html  # Three things dialog
    lead_id = next(a["id"] for a in edition["articles"] if a["slot"] == "lead")
    assert f'id="lead-{lead_id}"' in html
    cards = re.findall(r'<article id="card-([0-9a-f-]{36})"', html)
    others = [a["id"] for a in edition["articles"] if a["slot"] != "lead"]
    assert sorted(cards) == sorted(others)
    assert 'data-section-filter=""' in html and 'id="sheet"' in html
    assert i18n.t("home.progress", "en", read=0, total=len(edition["articles"])) in html
    assert 'aria-current="page"' in html  # bottom nav


def test_the_header_plays_the_sunrise_video_and_the_logo_files_are_served(
    client: TestClient, edition
) -> None:
    html = client.get("/paper/today").text
    assert 'class="hero-video"' in html and 'class="hero-video-overlay"' in html
    assert 'src="/static/logo-mark.png"' in html
    video = client.get("/static/video/subah_header_background.mp4")
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    assert client.get("/static/logo.webp").status_code == 200
    assert client.get("/static/logo-mark.png").status_code == 200
    assert (
        "/static/app.css?v=" in html
    )  # cache-busted so a deploy is never styled by old CSS


def test_the_edition_is_served_by_date_and_bad_dates_are_404(
    client: TestClient, edition
) -> None:
    assert client.get(f"/paper/{edition['day']}").status_code == 200
    assert client.get("/paper/2001-01-01").status_code == 404
    assert client.get("/paper/not-a-date").status_code == 404


def test_signed_out_and_not_onboarded_readers_are_sent_away(
    client: TestClient, edition, make_user, post_form
) -> None:
    anonymous = TestClient(app)
    for path in (f"/paper/{edition['day']}", "/paper/today"):
        response = anonymous.get(path, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (303, "/login")
    browser, _ = other_reader(make_user, post_form)
    response = browser.get(f"/paper/{edition['day']}", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/onboarding",
    )


def test_opening_the_sheet_marks_the_story_read_once_and_updates_the_page(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = next(a for a in edition["articles"] if a["slot"] != "lead")
    url = f"/paper/{edition['day']}/a/{art['id']}"
    sheet = client.get(url, headers={"HX-Request": "true"})
    assert sheet.status_code == 200 and "<html" not in sheet.text
    assert art["headline"] in sheet.text and f"/r/{art['id']}" in sheet.text
    assert (
        i18n.t("article.read_original", "en", source=art["articles"]["source_name"])
        in sheet.text
    )
    assert 'hx-swap-oob="outerHTML"' in sheet.text and "is-read" in sheet.text
    total = len(edition["articles"])
    assert i18n.t("home.progress", "en", read=1, total=total) in sheet.text
    client.get(url)  # a second visit must not double count
    assert len(signals(admin, onboarded_user.id, "open")) == 1
    page = client.get("/paper/today").text
    assert (
        "is-read" in page and i18n.t("home.progress", "en", read=1, total=total) in page
    )


def test_the_sheet_of_a_story_that_is_not_yours_is_404_and_leaves_no_trace(
    client: TestClient, edition, admin, make_user, post_form
) -> None:
    art = edition["articles"][1]
    browser, reader = other_reader(make_user, post_form)
    response = browser.get(f"/paper/{edition['day']}/a/{art['id']}")
    assert response.status_code == 404
    assert signals(admin, reader.id) == []
    assert client.get(f"/paper/{edition['day']}/a/not-a-uuid").status_code == 404
    anonymous = TestClient(app).get(
        f"/paper/{edition['day']}/a/{art['id']}", follow_redirects=False
    )
    assert anonymous.status_code == 303
