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
from email.utils import formatdate
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

# `pytest.ini` is at the repo root while this file is in `tests/`, so a bare `pytest`
# (as CI runs it) has no repo root on `sys.path` and cannot import `app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import deps, jobs
from app.config import settings
from app.main import app
from app.services import pdf

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
def no_browser_on_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chromium takes seconds to start; only the PDF tests need it (lazily, on the first PDF)."""

    async def skip(application) -> None:
        return None

    monkeypatch.setattr(pdf, "start_on_startup", skip)
    monkeypatch.setattr(jobs, "start_scheduler", lambda: None)


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
def onboarded_user(make_user, client: TestClient, post_form) -> TestUser:
    """User with a profile, 3 interests, 1 favorite source, and 1 muted keyword."""
    import json

    reader = make_user("Test Reader")
    login = post_form(client, "/login", email=reader.email, password=reader.password)
    assert login.status_code == 303, "onboarded_user could not log in"
    form = {
        "edition_lang": "en",
        "source_langs": ["en"],
        "topics": ["ai", "pakistan", "climate"],
        "topic_level_ai": "3",
        "topic_level_pakistan": "2",
        "topic_level_climate": "2",
        "taste": json.dumps([]),
        "custom_interests": json.dumps([]),
        "favorite_sources": json.dumps(["bbc"]),
        "custom_feeds": json.dumps([]),
        "muted_keywords": json.dumps(["cricket"]),
        "city": "Lahore",
        "timezone": "Asia/Karachi",
        "reading_minutes": "10",
        "notify": "0",
    }
    result = post_form(client, "/onboarding", **form)
    assert result.status_code == 303, f"onboarding failed: {result.text[:200]}"
    return reader


@pytest.fixture
def edition(onboarded_user, feeds_mock, fake_agents, monkeypatch, admin) -> dict:
    """Today's edition for `onboarded_user`, built with fake agents and mocked feeds.

    Returns `{"id", "day", "articles"}` where `articles` are its `edition_articles` rows
    (lead first) joined with their `articles` row.
    """
    import asyncio

    from app.agents import runner
    from app.services import edition as pipeline

    monkeypatch.setattr(runner, "run_agent", fake_agents)
    profile = asyncio.run(pipeline.get_profile(onboarded_user.id))
    day = pipeline.local_date_for(profile.timezone)
    edition_id = asyncio.run(pipeline.generate_edition(onboarded_user.id, day))
    rows = (
        admin.table("edition_articles")
        .select("*,articles(*)")
        .eq("edition_id", edition_id)
        .order("position")
        .execute()
        .data
    )
    assert rows, "the fixture edition has no articles"
    return {"id": edition_id, "day": day.isoformat(), "articles": rows}


def rss(titles: list[str], source: str = "Test Wire") -> str:
    """A minimal RSS document with fresh items (published a few minutes ago)."""
    stamp = formatdate(usegmt=True)
    items = "".join(
        f"<item><title>{t} - {source}</title><link>https://news.example.com/{uuid.uuid4().hex}</link>"
        f"<pubDate>{stamp}</pubDate><source url='https://x.example'>{source}</source></item>"
        for t in titles
    )
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>{items}</channel></rss>"


@pytest.fixture
def feeds_mock() -> Iterator[respx.MockRouter]:
    """respx router: Supabase traffic passes through, Google News search is generated per query.

    Every search returns 6 fresh stories with fully unique headlines (so the near-duplicate filter keeps them all). Add more routes
    (curated feeds, custom feeds) on the yielded router.
    """
    host = httpx.URL(settings.SUPABASE_URL).host
    with respx.mock(assert_all_called=False) as router:
        router.route(host=host).pass_through()

        def news_search(request: httpx.Request) -> httpx.Response:
            titles = [
                " ".join(uuid.uuid4().hex[:8] for _ in range(4)) for _ in range(6)
            ]
            return httpx.Response(200, text=rss(titles))

        router.get("https://news.google.com/rss/search").mock(side_effect=news_search)
        yield router


@pytest.fixture
def fake_agents():
    """Async callable suitable for monkeypatching `app.agents.runner.run_agent`.

    Parses candidate IDs from the curator/editor prompt and returns valid typed outputs.
    Returns `None` for unknown agent keys (triggers deterministic fallbacks).
    """
    import re as _re

    from app.models import CuratorOut, EditorOut, Pick, WrittenArticle

    async def _run_agent(key, factory, agent_input, edition_id, **_):
        if key == "curator":
            ids = _re.findall(r"<article>([a-f0-9]{12})", agent_input)
            n_match = _re.search(r"reading_time: (\d+) articles", agent_input)
            n = int(n_match.group(1)) if n_match else 6
            picks = [
                Pick(
                    candidate_id=cid,
                    section="world",
                    importance=10 if i == 0 else 5,
                    reason="test pick",
                )
                for i, cid in enumerate(ids[:n])
            ]
            return CuratorOut(picks=picks, notes="fake curator")
        if key == "editor":
            ids = _re.findall(r'<article id="([a-f0-9]{12})"', agent_input)
            articles = [
                WrittenArticle(
                    candidate_id=cid,
                    headline=f"Test headline {cid[:6]}",
                    summary="A test summary for this article today.",
                    why="Because you follow AI",
                )
                for cid in ids
            ]
            n = len(ids)
            three = [f"Fact {i + 1} from today's paper" for i in range(3)]
            return EditorOut(
                lead_headline="Test lead headline",
                lead_dek="Test dek line for the lead story.",
                articles=articles,
                section_titles={},
                three_things=three,
                editor_note="Good morning, Test Reader!",
                puzzle=[],
            )
        return None

    return _run_agent
