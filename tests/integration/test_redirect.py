"""`/r/{edition_article_id}`: logs the click, then 302s only to the stored URL (T-07)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration


def story(edition: dict) -> dict:
    return next(a for a in edition["articles"] if a["slot"] != "lead")


def test_the_redirect_goes_to_the_stored_url_and_records_a_click(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition)
    response = client.get(f"/r/{art['id']}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == art["articles"]["url"]
    clicks = (
        admin.table("signals")
        .select("*")
        .eq("user_id", onboarded_user.id)
        .eq("kind", "click")
        .execute()
        .data
    )
    assert [c["edition_article_id"] for c in clicks] == [art["id"]]


def test_a_clicked_story_counts_as_read(client: TestClient, edition) -> None:
    art = story(edition)
    client.get(f"/r/{art['id']}", follow_redirects=False)
    assert (
        f'id="card-{art["id"]}" class="story card fade-up is-read"'
        in client.get("/paper/today").text
    )


def test_a_url_in_the_query_string_is_never_followed(
    client: TestClient, edition
) -> None:
    art = story(edition)
    response = client.get(
        f"/r/{art['id']}?url=https://evil.example/phish&next=https://evil.example",
        follow_redirects=False,
    )
    assert response.headers["location"] == art["articles"]["url"]


def test_unknown_and_malformed_ids_are_404(client: TestClient, edition) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    for bad in (missing, "not-a-uuid", "1"):
        assert client.get(f"/r/{bad}", follow_redirects=False).status_code == 404


def test_signed_out_readers_go_to_login_and_strangers_get_404(
    edition, admin, make_user, post_form
) -> None:
    art = story(edition)
    anonymous = TestClient(app).get(f"/r/{art['id']}", follow_redirects=False)
    assert (anonymous.status_code, anonymous.headers["location"]) == (303, "/login")
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    assert browser.get(f"/r/{art['id']}", follow_redirects=False).status_code == 404
    leaked = (
        admin.table("signals").select("id").eq("user_id", stranger.id).execute().data
    )
    assert leaked == []
