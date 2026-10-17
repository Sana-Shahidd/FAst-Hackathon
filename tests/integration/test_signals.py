"""Feedback signals, dwell beacons and the save toggle (T-07: F-07, F-19)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.main import app

pytestmark = pytest.mark.integration


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/login")
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def story(edition: dict) -> dict:
    return next(a for a in edition["articles"] if a["slot"] != "lead")


def rows(admin, table: str, user_id: str, **match) -> list[dict]:
    query = admin.table(table).select("*").eq("user_id", user_id)
    for column, value in match.items():
        query = query.eq(column, value)
    return query.execute().data


def post_signal(client: TestClient, art_id: str, kind: str, **extra):
    return client.post(
        "/signals",
        data={"edition_article_id": art_id, "kind": kind, **extra},
        headers=csrf(client),
    )


def test_more_like_and_less_like_are_stored_once_and_shown_pressed(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition)
    for kind in ("more_like", "less_like"):
        first = post_signal(client, art["id"], kind)
        assert first.status_code == 200
        assert f'id="card-{art["id"]}"' in first.text
        post_signal(client, art["id"], kind)  # tapping again adds nothing
        assert len(rows(admin, "signals", onboarded_user.id, kind=kind)) == 1
    html = post_signal(client, art["id"], "more_like").text
    assert html.count('aria-pressed="true"') == 2  # both thumbs are shown pressed


def test_hiding_a_source_stores_the_signal_and_removes_the_card(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition)
    response = post_signal(client, art["id"], "skip_source")
    assert (response.status_code, response.text) == (200, "")
    signal = rows(admin, "signals", onboarded_user.id, kind="skip_source")
    assert [s["edition_article_id"] for s in signal] == [art["id"]]


def test_dwell_is_a_204_beacon_and_is_clamped(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition)
    assert post_signal(client, art["id"], "dwell", value="42").status_code == 204
    assert post_signal(client, art["id"], "dwell", value="999999").status_code == 204
    assert post_signal(client, art["id"], "dwell", value="-5").status_code == 204
    values = sorted(
        s["value"] for s in rows(admin, "signals", onboarded_user.id, kind="dwell")
    )
    assert values == [0, 42, 3600]


def test_signals_reject_bad_kinds_missing_csrf_and_strangers(
    client: TestClient, edition, admin, onboarded_user, make_user, post_form
) -> None:
    art = story(edition)
    assert (
        post_signal(client, art["id"], "open").status_code == 422
    )  # not a form signal
    assert post_signal(client, art["id"], "nonsense").status_code == 422
    no_csrf = client.post(
        "/signals", data={"edition_article_id": art["id"], "kind": "more_like"}
    )
    assert no_csrf.status_code == 403
    assert post_signal(client, "not-a-uuid", "more_like").status_code == 404
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    blocked = browser.post(
        "/signals",
        data={"edition_article_id": art["id"], "kind": "more_like"},
        headers=csrf(browser),
    )
    assert blocked.status_code == 404
    assert rows(admin, "signals", stranger.id) == []
    assert rows(admin, "signals", onboarded_user.id) == []


def test_saving_toggles_the_bookmark_and_records_one_save_signal(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition)
    saved = client.post(f"/saved/{art['id']}", headers=csrf(client))
    assert saved.status_code == 200 and "is-on" in saved.text
    stored = rows(admin, "saved_articles", onboarded_user.id)
    assert [(r["edition_article_id"], r["article_id"]) for r in stored] == [
        (art["id"], art["article_id"])
    ]
    assert len(rows(admin, "signals", onboarded_user.id, kind="save")) == 1

    removed = client.post(f"/saved/{art['id']}", headers=csrf(client))
    assert "is-on" not in removed.text
    assert rows(admin, "saved_articles", onboarded_user.id) == []

    client.post(f"/saved/{art['id']}", headers=csrf(client))  # save again
    assert len(rows(admin, "saved_articles", onboarded_user.id)) == 1
    assert (
        len(rows(admin, "signals", onboarded_user.id, kind="save")) == 1
    )  # no double count
    assert "is-on" in client.get("/paper/today").text  # the page remembers


def test_saving_from_the_sheet_returns_the_sheet(
    client: TestClient, edition, onboarded_user
) -> None:
    art = story(edition)
    response = client.post(
        f"/saved/{art['id']}", data={"ctx": "sheet"}, headers=csrf(client)
    )
    assert 'class="sheet"' in response.text and 'id="sheet-save"' in response.text
    assert "is-on" in response.text


def test_saving_needs_csrf_login_and_your_own_story(
    client: TestClient, edition, admin, make_user, post_form
) -> None:
    art = story(edition)
    assert client.post(f"/saved/{art['id']}").status_code == 403
    anonymous = TestClient(app)
    anonymous.get("/login")
    response = anonymous.post(
        f"/saved/{art['id']}", headers=csrf(anonymous), follow_redirects=False
    )
    assert response.status_code == 401 or response.status_code == 303
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    assert browser.post(f"/saved/{art['id']}", headers=csrf(browser)).status_code == 404
    assert rows(admin, "saved_articles", stranger.id) == []
