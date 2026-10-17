"""Signup, login, logout and sessions against the real test Supabase project."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthError

from app import deps
from app.services import i18n
from app.services.onboarding import default_name

pytestmark = pytest.mark.integration


@pytest.fixture
def new_email(admin):
    """A fresh address for a form signup; the account it creates is deleted afterwards."""
    email = f"it-{uuid.uuid4().hex[:12]}@subah.test"
    yield email
    for found in admin.auth.admin.list_users(per_page=200):
        if found.email == email:
            admin.auth.admin.delete_user(str(found.id))


def cookie_names(response) -> set[str]:
    return {c.split("=", 1)[0] for c in response.headers.get_list("set-cookie")}


def test_health_reports_a_working_database(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["db"] is True


def test_signup_creates_the_account_profile_and_session(
    client: TestClient, admin, post_form, new_email: str
) -> None:
    response = post_form(client, "/signup", email=new_email, password="a-good-passw0rd")
    assert response.status_code == 303, response.text[:300]
    assert response.headers["location"] == "/onboarding"
    assert {"sb_access", "sb_refresh"} <= cookie_names(response)
    expected = default_name(new_email)
    rows = admin.table("profiles").select("display_name,onboarded_at").execute().data
    assert any(
        r["display_name"] == expected and r["onboarded_at"] is None for r in rows
    )


def test_signing_up_twice_with_one_email_shows_the_exists_message(
    client: TestClient, post_form, new_email: str
) -> None:
    first = post_form(client, "/signup", email=new_email, password="a-good-passw0rd")
    assert first.status_code == 303
    second = post_form(
        TestClient(client.app), "/signup", email=new_email, password="a-good-passw0rd"
    )
    assert second.status_code == 400
    assert i18n.t("auth.error.exists", "en") in second.text


def test_short_password_is_rejected_with_a_message(
    client: TestClient, post_form, new_email: str
) -> None:
    response = post_form(client, "/signup", email=new_email, password="123")
    assert response.status_code == 400
    assert i18n.t("auth.error.weak", "en") in response.text


def test_login_sets_cookies_and_sends_a_new_reader_to_onboarding(
    client: TestClient, make_user, post_form
) -> None:
    reader = make_user()
    response = post_form(client, "/login", email=reader.email, password=reader.password)
    assert response.status_code == 303
    assert response.headers["location"] == "/onboarding"
    assert {"sb_access", "sb_refresh"} <= cookie_names(response)
    set_cookies = " ".join(response.headers.get_list("set-cookie")).lower()
    assert "httponly" in set_cookies and "samesite=lax" in set_cookies


def test_an_onboarded_reader_logs_in_to_todays_paper(
    client: TestClient, make_user, admin, post_form
) -> None:
    reader = make_user()
    admin.table("profiles").update({"onboarded_at": "2026-10-17T05:00:00+00:00"}).eq(
        "user_id", reader.id
    ).execute()
    response = post_form(client, "/login", email=reader.email, password=reader.password)
    assert response.headers["location"] == "/paper/today"


def test_wrong_password_shows_the_message_and_sets_no_session(
    client: TestClient, make_user, post_form
) -> None:
    reader = make_user()
    response = post_form(
        client, "/login", email=reader.email, password="not-the-password"
    )
    assert response.status_code == 400
    assert i18n.t("auth.error.credentials", "en") in response.text
    assert not ({"sb_access", "sb_refresh"} & cookie_names(response))


def test_logout_clears_the_cookies_and_revokes_the_session(
    client: TestClient, user
) -> None:
    access = client.cookies.get("sb_access")
    assert access
    token = deps._sign(client.cookies.get("sb_csrf"))
    response = client.post(
        "/logout", data={"csrf_token": token}, follow_redirects=False
    )
    assert (response.status_code, response.headers["location"]) == (303, "/")
    assert client.cookies.get("sb_access") is None
    assert client.cookies.get("sb_refresh") is None
    assert (
        client.get("/paper/today", follow_redirects=False).headers["location"]
        == "/login"
    )
    with pytest.raises(AuthError):  # the old access token is dead server-side too
        deps.supabase_anon().auth.get_user(access)


def test_a_logged_in_session_passes_require_user(
    app_client_no_raise, make_user
) -> None:
    reader = make_user()
    app_client_no_raise.cookies.set("sb_access", reader.access_token)
    response = app_client_no_raise.get("/paper/today", follow_redirects=False)
    # past require_user -> not onboarded -> redirects to /onboarding, never to /login
    assert response.status_code == 303
    assert response.headers["location"] == "/onboarding"


def test_an_expired_access_token_is_renewed_with_the_refresh_token(
    make_user, admin
) -> None:
    from app.main import app

    reader = make_user()
    admin.table("profiles").update({"onboarded_at": "2026-10-17T05:00:00+00:00"}).eq(
        "user_id", reader.id
    ).execute()
    browser = TestClient(app)
    browser.cookies.set("sb_access", "expired.or.garbage")
    browser.cookies.set("sb_refresh", reader.refresh_token)
    response = browser.get("/", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/paper/today")
    assert {"sb_access", "sb_refresh"} <= cookie_names(response)


@pytest.fixture
def app_client_no_raise() -> TestClient:
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)
