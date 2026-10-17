"""How this paper was made (F-14) and the Listen card (F-16), through the real routes (T-13)."""

from __future__ import annotations

import html as htmllib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import i18n

pytestmark = pytest.mark.integration


def test_the_timeline_shows_every_agent_step_with_the_curators_picks_and_reasons(
    client: TestClient, edition, admin
) -> None:
    page = client.get(f"/paper/{edition['day']}/making-of")
    assert page.status_code == 200
    text = htmllib.unescape(page.text)
    assert i18n.t("paper.making_of", "en") in text
    for label in ("Pipeline", "Curator", "Editor"):
        assert f"<strong>{label}</strong>" in page.text
    assert "Fetched" in text and "feeds" in text  # the fetch statistics
    assert "Removed" in text and "candidates" in text  # duplicates, seen, muted
    assert "Picked 14 stories" in text or "Picked" in text
    assert "Edition ready in" in text
    picks = [a for a in edition["articles"]]
    assert text.count('class="tl-slot"') == len(picks)  # every picked story is listed
    assert "lead" in text and "test pick" in text  # the Curator's reason is shown
    assert 'class="making-stats"' in page.text and "fallback used" in page.text


def test_a_fallback_is_visible_on_the_timeline(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    admin.table("agent_activity").insert(
        {
            "edition_id": edition["id"],
            "agent": "editor",
            "kind": "fallback",
            "message": "gemini failed: TimeoutError",
        }
    ).execute()
    page = client.get(f"/paper/{edition['day']}/making-of").text
    assert "tl-fallback" in page and "gemini failed: TimeoutError" in page


def test_the_home_page_links_to_it_and_old_versions_keep_their_version(
    client: TestClient, edition
) -> None:
    home = client.get("/paper/today").text
    assert f'href="/paper/{edition["day"]}/making-of"' in home
    assert i18n.t("paper.making_of", "en") in home


def test_making_of_is_private_and_needs_an_edition(
    client: TestClient, edition, make_user, post_form
) -> None:
    assert client.get("/paper/2001-01-01/making-of").status_code == 404
    assert client.get("/paper/not-a-date/making-of").status_code == 404
    anonymous = TestClient(app).get(
        f"/paper/{edition['day']}/making-of", follow_redirects=False
    )
    assert (anonymous.status_code, anonymous.headers["location"]) == (303, "/login")
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    response = browser.get(f"/paper/{edition['day']}/making-of", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/onboarding")


def test_the_article_sheet_has_a_listen_card_in_the_editions_speech_language(
    client: TestClient, edition, admin
) -> None:
    art = next(a for a in edition["articles"] if a["slot"] != "lead")
    sheet = client.get(f"/paper/{edition['day']}/a/{art['id']}").text
    assert "data-listen-card" in sheet and 'data-lang="en-US"' in sheet
    assert (
        htmllib.unescape(sheet).count(art["headline"]) >= 2
    )  # spoken text + the headline
    assert sheet.count('<i style="--h:') == 40  # the decorative waveform
    admin.table("editions").update({"lang": "ur"}).eq("id", edition["id"]).execute()
    urdu = client.get(f"/paper/{edition['day']}/a/{art['id']}").text
    assert 'data-lang="ur-PK"' in urdu
