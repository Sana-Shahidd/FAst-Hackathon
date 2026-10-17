"""Shared pytest fixtures (docs/09_SETUP_TEST_DEMO.md §2).

`client`, `admin`, `make_user`, `user` and `post_form` are real (T-04). The rest are
skeletons filled in by the task that first needs them; until then they raise so no test
can quietly pass against a stub.
"""

from __future__ import annotations

import re
import sys
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# `pytest.ini` is at the repo root while this file is in `tests/`, so a bare `pytest`
# (as CI runs it) has no repo root on `sys.path` and cannot import `app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import deps
from app.config import settings
from app.main import app

TEST_PASSWORD = "it-Passw0rd!"


def _clear_supabase_cache() -> None:
    clear = getattr(deps.supabase_admin, "cache_clear", None)
    if clear:
        clear()


@pytest.fixture(autouse=True)
def use_test_supabase(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the app at the TEST Supabase project when `TEST_SUPABASE_*` is set.

    CI sets `SUPABASE_*` to the test project directly, so nothing changes there.
    """
    if settings.TEST_SUPABASE_URL and settings.TEST_SUPABASE_SERVICE_ROLE_KEY:
        monkeypatch.setattr(settings, "SUPABASE_URL", settings.TEST_SUPABASE_URL)
        monkeypatch.setattr(
            settings, "SUPABASE_ANON_KEY", settings.TEST_SUPABASE_ANON_KEY
        )
        monkeypatch.setattr(
            settings,
            "SUPABASE_SERVICE_ROLE_KEY",
            settings.TEST_SUPABASE_SERVICE_ROLE_KEY,
        )
    _clear_supabase_cache()
    yield
    _clear_supabase_cache()


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    """Rate limits are per client IP; every test starts with a clean slate."""
    deps.limiter.reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """FastAPI TestClient over the real app (lifespan runs)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin():
    """Service-role Supabase client of the test project (real network)."""
    return deps.supabase_admin()


@dataclass
class TestUser:
    __test__ = False  # not a test class

    id: str
    email: str
    password: str
    access_token: str
    refresh_token: str


@pytest.fixture
def make_user(admin) -> Iterator[Callable[..., TestUser]]:
    """Factory for `it-<uuid>@subah.test` users with a profile; all deleted in teardown."""
    created: list[str] = []

    def create(display_name: str = "Test Reader") -> TestUser:
        email = f"it-{uuid.uuid4().hex[:12]}@subah.test"
        made = admin.auth.admin.create_user(
            {"email": email, "password": TEST_PASSWORD, "email_confirm": True}
        )
        user_id = str(made.user.id)
        created.append(user_id)
        admin.table("profiles").upsert(
            {"user_id": user_id, "display_name": display_name}, on_conflict="user_id"
        ).execute()
        session = (
            deps.supabase_anon()
            .auth.sign_in_with_password({"email": email, "password": TEST_PASSWORD})
            .session
        )
        return TestUser(
            user_id, email, TEST_PASSWORD, session.access_token, session.refresh_token
        )

    yield create
    for user_id in created:
        try:
            admin.auth.admin.delete_user(user_id)  # cascades every row of that user
        except Exception as exc:  # noqa: BLE001 - never mask the test result with cleanup
            print(f"could not delete test user {user_id}: {exc}")


@pytest.fixture
def user(make_user, client: TestClient, post_form) -> TestUser:
    """A created test user, logged in through the real login form (cookies set on `client`)."""
    reader = make_user()
    response = post_form(client, "/login", email=reader.email, password=reader.password)
    assert response.status_code == 303, "test user could not log in"
    return reader


@pytest.fixture
def post_form() -> Callable[..., object]:
    """POST a form like a browser: GET it first for the CSRF cookie + hidden token."""

    def post(client: TestClient, path: str, **fields: str):
        page = client.get(path)
        match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page.text)
        assert match, f"no CSRF token on {path}"
        return client.post(
            path, data={**fields, "csrf_token": match.group(1)}, follow_redirects=False
        )

    return post


@pytest.fixture
def onboarded_user() -> None:
    """User with a profile, 5 interests, 2 favorite sources and 1 muted keyword."""
    raise NotImplementedError("F-02: onboarded user fixture arrives in T-05")


@pytest.fixture
def edition() -> None:
    """Edition generated with fake agent outputs and mocked feeds."""
    raise NotImplementedError("F-05: edition fixture arrives with the pipeline in T-06")


@pytest.fixture
def feeds_mock() -> None:
    """respx router serving `tests/fixtures/*.xml` instead of real feeds."""
    raise NotImplementedError("F-04: feeds_mock fixture arrives with feeds in T-03")


@pytest.fixture
def fake_agents() -> None:
    """Fixed CuratorOut/EditorOut/LearnerOut/ProfilerOut, or None to force fallbacks."""
    raise NotImplementedError("F-05: fake_agents fixture arrives with agents in T-02")
