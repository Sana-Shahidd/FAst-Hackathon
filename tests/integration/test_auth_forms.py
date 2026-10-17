"""Signup / login / logout / session refresh through the real routes, Supabase scripted.

These run without Supabase credentials. `test_auth.py` repeats the flows against the real
test project once `TEST_SUPABASE_*` are available.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from app import deps
from app.main import app
from app.services import i18n

pytestmark = pytest.mark.integration


def make_session(user_id: str, email: str, suffix: str = "1") -> SimpleNamespace:
    user = SimpleNamespace(id=user_id, email=email)
    return SimpleNamespace(
        access_token=f"access-{user_id}-{suffix}",
        refresh_token=f"refresh-{user_id}-{suffix}",
        user=user,
    )


class World:
    """In-memory stand-in for Supabase Auth + the `profiles` table."""

    def __init__(self) -> None:
        self.users: dict[str, tuple[str, str]] = {}  # email -> (id, password)
        self.access: dict[str, SimpleNamespace] = {}  # access token -> user
        self.refresh: dict[str, SimpleNamespace] = {}  # refresh token -> user
        self.profiles: dict[str, dict] = {}
        self.upserts: list[dict] = []
        self.revoked: list[str] = []
        self.sign_up_calls = 0
        self.fail_with: Exception | None = None

    def issue(self, user_id: str, email: str, suffix: str = "1") -> SimpleNamespace:
        session = make_session(user_id, email, suffix)
        self.access[session.access_token] = session.user
        self.refresh[session.refresh_token] = session.user
        return session


class FakeAuth:
    def __init__(self, world: World) -> None:
        self.world = world

    def sign_up(self, creds: dict) -> SimpleNamespace:
        self.world.sign_up_calls += 1
        if self.world.fail_with:
            raise self.world.fail_with
        email, password = creds["email"], creds["password"]
        if email in self.world.users:
            raise AuthApiError("User already registered", 422, "user_already_exists")
        user_id = f"user-{len(self.world.users) + 1}"
        self.world.users[email] = (user_id, password)
        session = self.world.issue(user_id, email)
        return SimpleNamespace(user=session.user, session=session)

    def sign_in_with_password(self, creds: dict) -> SimpleNamespace:
        found = self.world.users.get(creds["email"])
        if not found or found[1] != creds["password"]:
            raise AuthApiError("Invalid login credentials", 400, "invalid_credentials")
        session = self.world.issue(found[0], creds["email"], "login")
        return SimpleNamespace(user=session.user, session=session)

    def get_user(self, token: str) -> SimpleNamespace:
        if token not in self.world.access:
            raise AuthApiError("invalid JWT", 401, "bad_jwt")
        return SimpleNamespace(user=self.world.access[token])

    def refresh_session(self, token: str) -> SimpleNamespace:
        user = self.world.refresh.get(token)
        if not user:
            raise AuthApiError(
                "refresh token not found", 400, "refresh_token_not_found"
            )
        session = self.world.issue(user.id, user.email, "renewed")
        return SimpleNamespace(session=session, user=user)


class FakeTable:
    def __init__(self, world: World) -> None:
        self.world, self.row, self.mode, self.uid = world, None, "select", None

    def upsert(self, row: dict, **_: object) -> FakeTable:
        self.mode, self.row = "upsert", row
        return self

    def select(self, *_: object) -> FakeTable:
        return self

    def eq(self, _column: str, value: str) -> FakeTable:
        self.uid = value
        return self

    def limit(self, _n: int) -> FakeTable:
        return self

    def execute(self) -> SimpleNamespace:
        if self.mode == "upsert":
            self.world.upserts.append(self.row)
            self.world.profiles.setdefault(
                self.row["user_id"], {**self.row, "onboarded_at": None}
            )
            return SimpleNamespace(data=[self.row])
        profile = self.world.profiles.get(self.uid)
        return SimpleNamespace(data=[profile] if profile else [])


class FakeAdmin:
    def __init__(self, world: World) -> None:
        self.world = world
        self.auth = SimpleNamespace(admin=SimpleNamespace(sign_out=self.sign_out))

    def table(self, name: str) -> FakeTable:
        assert name == "profiles"
        return FakeTable(self.world)

    def sign_out(self, token: str) -> None:
        self.world.revoked.append(token)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    state = World()
    monkeypatch.setattr(
        deps, "supabase_anon", lambda: SimpleNamespace(auth=FakeAuth(state))
    )
    monkeypatch.setattr(deps, "supabase_admin", lambda: FakeAdmin(state))
    return state


def submit(client: TestClient, path: str, **fields: str):
    """GET the form for its CSRF token/cookie, then POST it like a browser."""
    page = client.get(path)
    token = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page.text).group(1)
    return client.post(
        path, data={**fields, "csrf_token": token}, follow_redirects=False
    )


def cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_signup_creates_the_account_profile_and_session(
    client: TestClient, world: World
) -> None:
    response = submit(
        client, "/signup", email="Reader@Example.com ", password="s3cret-pw"
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/onboarding"
    assert "reader@example.com" in world.users  # trimmed and lower-cased
    assert world.upserts == [{"user_id": "user-1", "display_name": "Reader"}]
    cookies = {c.split("=")[0]: c for c in cookie_headers(response)}
    for name in ("sb_access", "sb_refresh"):
        assert "httponly" in cookies[name].lower()
        assert "samesite=lax" in cookies[name].lower()
    assert client.cookies.get("sb_access") == "access-user-1-1"


def test_signup_with_an_existing_email_shows_the_exists_message(
    client: TestClient, world: World
) -> None:
    world.users["taken@example.com"] = ("user-9", "whatever")
    response = submit(
        client, "/signup", email="taken@example.com", password="s3cret-pw"
    )
    assert response.status_code == 400
    assert i18n.t("auth.error.exists", "en") in response.text
    assert 'value="taken@example.com"' in response.text  # the form keeps what was typed
    assert not any(c.startswith("sb_access") for c in cookie_headers(response))
    assert world.upserts == []


@pytest.mark.parametrize(
    ("email", "password"), [("not-an-email", "s3cret-pw"), ("a@b.co", "123"), ("", "")]
)
def test_signup_rejects_bad_input_without_calling_supabase(
    client: TestClient, world: World, email: str, password: str
) -> None:
    response = submit(client, "/signup", email=email, password=password)
    assert response.status_code == 400
    assert i18n.t("auth.error.weak", "en") in response.text
    assert world.sign_up_calls == 0


def test_errors_are_shown_in_the_readers_language(
    client: TestClient, world: World
) -> None:
    client.get("/signup?lang=ur")
    world.users["taken@example.com"] = ("user-9", "x")
    response = submit(
        client, "/signup", email="taken@example.com", password="s3cret-pw"
    )
    assert i18n.t("auth.error.exists", "ur") in response.text
    assert 'dir="rtl"' in response.text


def test_login_goes_to_onboarding_until_the_profile_is_finished(
    client: TestClient, world: World
) -> None:
    world.users["a@b.co"] = ("user-1", "right-pw")
    world.profiles["user-1"] = {"user_id": "user-1", "onboarded_at": None}
    response = submit(client, "/login", email="a@b.co", password="right-pw")
    assert (response.status_code, response.headers["location"]) == (303, "/onboarding")
    assert client.cookies.get("sb_access")


def test_login_of_an_onboarded_reader_goes_to_todays_paper(
    client: TestClient, world: World
) -> None:
    world.users["a@b.co"] = ("user-1", "right-pw")
    world.profiles["user-1"] = {
        "user_id": "user-1",
        "onboarded_at": "2026-10-17T05:00:00Z",
    }
    response = submit(client, "/login", email="a@b.co", password="right-pw")
    assert response.headers["location"] == "/paper/today"


def test_wrong_password_shows_a_message_and_sets_no_cookies(
    client: TestClient, world: World
) -> None:
    world.users["a@b.co"] = ("user-1", "right-pw")
    response = submit(client, "/login", email="a@b.co", password="wrong-pw")
    assert response.status_code == 400
    assert i18n.t("auth.error.credentials", "en") in response.text
    assert 'value="a@b.co"' in response.text
    assert not any(
        c.startswith("sb_") and "sb_csrf" not in c for c in cookie_headers(response)
    )


def test_unexpected_backend_failure_shows_a_friendly_error_not_a_stack_trace(
    client: TestClient, world: World
) -> None:
    world.fail_with = RuntimeError("connection reset by peer 10.0.0.7")
    response = submit(client, "/signup", email="a@b.co", password="s3cret-pw")
    assert response.status_code == 500
    assert i18n.t("auth.error.generic", "en") in response.text
    assert "10.0.0.7" not in response.text and "Traceback" not in response.text


def test_logout_revokes_the_session_and_clears_cookies(
    client: TestClient, world: World
) -> None:
    world.users["a@b.co"] = ("user-1", "right-pw")
    submit(client, "/login", email="a@b.co", password="right-pw")
    access = client.cookies.get("sb_access")
    assert access
    csrf = deps._sign(client.cookies.get("sb_csrf"))
    out = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
    assert (out.status_code, out.headers["location"]) == (303, "/")
    assert world.revoked == [access]
    assert client.cookies.get("sb_access") is None
    assert client.cookies.get("sb_refresh") is None
    assert (
        client.get("/paper/today", follow_redirects=False).headers["location"]
        == "/login"
    )


def test_logout_requires_a_login(client: TestClient, world: World) -> None:
    client.get("/login")
    csrf = deps._sign(client.cookies.get("sb_csrf"))
    out = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
    assert (out.status_code, out.headers["location"]) == (303, "/login")


def test_signed_in_visitors_skip_the_landing_page(
    client: TestClient, world: World
) -> None:
    world.users["a@b.co"] = ("user-1", "right-pw")
    world.profiles["user-1"] = {
        "user_id": "user-1",
        "onboarded_at": "2026-10-17T05:00:00Z",
    }
    submit(client, "/login", email="a@b.co", password="right-pw")
    response = client.get("/", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/paper/today")


def test_a_valid_session_reaches_protected_routes(world: World) -> None:
    session = world.issue("user-1", "a@b.co")
    browser = TestClient(app, raise_server_exceptions=False)
    browser.cookies.set("sb_access", session.access_token)
    response = browser.get("/paper/today", follow_redirects=False)
    # Authenticated: it got past require_user -> no profile -> redirects to /onboarding.
    assert response.status_code == 303
    assert response.headers["location"] == "/onboarding"


def test_an_expired_access_token_is_renewed_from_the_refresh_token(
    world: World,
) -> None:
    session = world.issue("user-1", "a@b.co")
    world.profiles["user-1"] = {
        "user_id": "user-1",
        "onboarded_at": "2026-10-17T05:00:00Z",
    }
    browser = TestClient(app)
    browser.cookies.set("sb_access", "expired-token")
    browser.cookies.set("sb_refresh", session.refresh_token)
    response = browser.get("/", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/paper/today")
    renewed = {c.split("=")[0]: c for c in cookie_headers(response)}
    assert renewed["sb_access"].startswith("sb_access=access-user-1-renewed")
    assert renewed["sb_refresh"].startswith("sb_refresh=refresh-user-1-renewed")
    assert "httponly" in renewed["sb_refresh"].lower()


def test_garbage_session_cookies_mean_signed_out(world: World) -> None:
    browser = TestClient(app)
    browser.cookies.set("sb_access", "garbage")
    browser.cookies.set("sb_refresh", "garbage")
    assert (
        browser.get("/paper/today", follow_redirects=False).headers["location"]
        == "/login"
    )


def test_signup_is_rate_limited_to_five_a_minute(
    client: TestClient, world: World
) -> None:
    statuses = [
        submit(
            client, "/signup", email=f"user{n}@example.com", password="s3cret-pw"
        ).status_code
        for n in range(6)
    ]
    assert statuses[:5] == [303] * 5
    assert statuses[5] == 429
