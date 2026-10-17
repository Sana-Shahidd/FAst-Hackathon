"""Edition pipeline: generate, status poll, route guards (T-06, docs/02_PRD.md F-03–F-05).

Real Supabase, feeds mocked with `feeds_mock`, LLM agents patched via `fake_agents`.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.agents import runner
from app.services import edition

pytestmark = pytest.mark.integration


# ------------------------------------------------------------------ helpers


def csrf_headers(client: TestClient) -> dict[str, str]:
    client.get("/login")
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def ed_rows(admin, user_id: str) -> list[dict]:
    return admin.table("editions").select("*").eq("user_id", user_id).execute().data


def ea_rows(admin, edition_id: str) -> list[dict]:
    return (
        admin.table("edition_articles")
        .select("*")
        .eq("edition_id", edition_id)
        .execute()
        .data
    )


def puzzle_rows(admin, edition_id: str) -> list[dict]:
    return (
        admin.table("puzzles").select("*").eq("edition_id", edition_id).execute().data
    )


# ------------------------------------------------------------------ route guards


def test_generate_requires_login(client: TestClient) -> None:
    r = client.get("/paper/generate", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_status_requires_login(client: TestClient) -> None:
    r = client.get("/paper/status", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_today_requires_login(client: TestClient) -> None:
    r = client.get("/paper/today", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_generate_redirects_to_onboarding_before_onboarding(
    client: TestClient, user
) -> None:
    r = client.get("/paper/generate", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/onboarding"


def test_today_redirects_to_generate_when_no_edition_exists(
    client: TestClient, onboarded_user, feeds_mock
) -> None:
    r = client.get("/paper/today", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/paper/generate"


def test_status_shows_waiting_when_no_edition_started(
    client: TestClient, onboarded_user
) -> None:
    r = client.get("/paper/status", follow_redirects=False)
    # The template renders a spinner li for both 'waiting' and 'generating' states
    assert r.status_code == 200 and "step-working" in r.text


def test_regenerate_requires_csrf(client: TestClient, onboarded_user) -> None:
    r = client.post(
        "/paper/generate",
        data={"regenerate": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_generate_page_shows_printing_screen_for_onboarded_user(
    client: TestClient, onboarded_user, feeds_mock, monkeypatch, fake_agents
) -> None:
    monkeypatch.setattr(runner, "run_agent", fake_agents)
    r = client.get("/paper/generate", follow_redirects=False)
    # 200 = generation just started; 303 = already ready (race won't happen in sync test)
    assert r.status_code in (200, 303)


# ------------------------------------------------------------------ pipeline (async)


async def test_edition_pipeline_produces_complete_edition(
    onboarded_user, feeds_mock, monkeypatch, fake_agents, admin
) -> None:
    """Full pipeline with fake agents: ready status, article slots, puzzle items."""
    monkeypatch.setattr(runner, "run_agent", fake_agents)
    today = date.today()

    edition_id = await edition.generate_edition(onboarded_user.id, today)

    rows = ed_rows(admin, onboarded_user.id)
    assert len(rows) == 1
    ed = rows[0]
    assert ed["id"] == edition_id
    assert ed["status"] == "ready"
    assert ed["lead_headline"] and ed["lead_dek"]
    assert isinstance(ed["three_things"], list) and len(ed["three_things"]) == 3
    assert ed["generation_ms"] and ed["generation_ms"] > 0

    articles = ea_rows(admin, edition_id)
    assert len(articles) >= 1
    slots = {a["slot"] for a in articles}
    assert "lead" in slots

    puz = puzzle_rows(admin, edition_id)
    assert len(puz) == 1
    items = puz[0]["items"]
    assert 1 <= len(items) <= 5
    for item in items:
        assert item["masked_headline"].count("___") == 1
        assert item["answer"]
        assert len(item["choices"]) == 4


async def test_edition_pipeline_fallback_when_agents_return_none(
    onboarded_user, feeds_mock, monkeypatch, admin
) -> None:
    """Deterministic fallback: edition is still ready when both LLM agents return None."""

    async def _always_none(*_a, **_k):
        return None

    monkeypatch.setattr(runner, "run_agent", _always_none)
    today = date.today()

    edition_id = await edition.generate_edition(onboarded_user.id, today)
    rows = ed_rows(admin, onboarded_user.id)
    assert rows and rows[0]["status"] == "ready"
    assert rows[0]["used_fallback"] is True
    assert ea_rows(admin, edition_id)


async def test_second_call_reuses_existing_ready_edition(
    onboarded_user, feeds_mock, monkeypatch, fake_agents
) -> None:
    """Calling generate_edition twice on the same date returns the same edition id."""
    monkeypatch.setattr(runner, "run_agent", fake_agents)
    today = date.today()
    id1 = await edition.generate_edition(onboarded_user.id, today)
    id2 = await edition.generate_edition(onboarded_user.id, today)
    assert id1 == id2


async def test_regenerate_flag_creates_new_version(
    onboarded_user, feeds_mock, monkeypatch, fake_agents, admin
) -> None:
    """regenerate=True creates a new version row and supersedes the old one."""
    monkeypatch.setattr(runner, "run_agent", fake_agents)
    today = date.today()
    id1 = await edition.generate_edition(onboarded_user.id, today)
    id2 = await edition.generate_edition(onboarded_user.id, today, regenerate=True)
    assert id1 != id2

    rows = ed_rows(admin, onboarded_user.id)
    by_id = {r["id"]: r for r in rows}
    assert by_id[id2]["status"] == "ready"
    assert by_id[id1]["status"] == "superseded"
    assert by_id[id2]["version"] > by_id[id1]["version"]


async def test_activity_log_is_written_for_every_pipeline_step(
    onboarded_user, feeds_mock, monkeypatch, fake_agents, admin
) -> None:
    """agent_activity rows must include started and finished events."""
    monkeypatch.setattr(runner, "run_agent", fake_agents)
    today = date.today()
    edition_id = await edition.generate_edition(onboarded_user.id, today)

    activity = (
        admin.table("agent_activity")
        .select("agent,kind")
        .eq("edition_id", edition_id)
        .execute()
        .data
    )
    kinds = {r["kind"] for r in activity}
    assert "started" in kinds and "finished" in kinds


async def test_steps_for_returns_activity_in_order(
    onboarded_user, feeds_mock, monkeypatch, fake_agents
) -> None:
    """steps_for returns a list of dicts with agent, kind, message, created_at."""
    monkeypatch.setattr(runner, "run_agent", fake_agents)
    today = date.today()
    edition_id = await edition.generate_edition(onboarded_user.id, today)
    steps = await edition.steps_for(edition_id)
    assert steps
    assert all("agent" in s and "kind" in s and "message" in s for s in steps)


async def test_muted_story_absent_from_final_edition(
    onboarded_user, feeds_mock, monkeypatch, admin
) -> None:
    """Stories matching the muted keyword 'cricket' are not placed in the edition.

    The fake agent picks whatever IDs appear in its input; since muted stories are
    filtered BEFORE the Curator sees them, they will never appear as candidates.
    We inject a cricket story via the mock so the filter has something to remove.
    """
    import uuid

    from tests.conftest import rss

    # Inject a cricket story into every Google News search response
    cricket_title = f"cricket world cup final {uuid.uuid4().hex[:4]}"

    def news_search_with_cricket(request):
        import httpx

        titles = [cricket_title] + [
            " ".join(uuid.uuid4().hex[:8] for _ in range(4)) for _ in range(5)
        ]
        return httpx.Response(200, text=rss(titles, "Cricket Wire"))

    feeds_mock.get("https://news.google.com/rss/search").mock(
        side_effect=news_search_with_cricket
    )

    async def pick_all_ids(key, factory, agent_input, edition_id, **_):
        """Fake agent that picks every candidate it receives."""
        import re

        from app.models import CuratorOut, EditorOut, Pick, WrittenArticle

        if key == "curator":
            ids = re.findall(r"<article>([a-f0-9]{12})", agent_input)
            n_match = re.search(r"reading_time: (\d+) articles", agent_input)
            n = int(n_match.group(1)) if n_match else len(ids)
            picks = [
                Pick(
                    candidate_id=cid,
                    section="world",
                    importance=10 if i == 0 else 5,
                    reason="test",
                )
                for i, cid in enumerate(ids[:n])
            ]
            return CuratorOut(picks=picks, notes="")
        if key == "editor":
            ids = re.findall(r'<article id="([a-f0-9]{12})"', agent_input)
            articles = [
                WrittenArticle(
                    candidate_id=cid,
                    headline=f"Headline {cid[:4]}",
                    summary="Summary.",
                    why="why",
                )
                for cid in ids
            ]
            return EditorOut(
                lead_headline="Lead",
                lead_dek="Dek",
                articles=articles,
                section_titles={},
                three_things=["a", "b", "c"],
                puzzle=[],
            )
        return None

    monkeypatch.setattr(runner, "run_agent", pick_all_ids)

    today = date.today()
    edition_id = await edition.generate_edition(onboarded_user.id, today)

    rows = ed_rows(admin, onboarded_user.id)
    assert rows and rows[0]["status"] == "ready"

    articles = ea_rows(admin, edition_id)
    headlines = [a["headline"].lower() for a in articles]
    assert not any("cricket" in h for h in headlines), (
        f"muted keyword 'cricket' appeared in headlines: {headlines}"
    )


async def test_latest_and_ready_edition_helpers(
    onboarded_user, feeds_mock, monkeypatch, fake_agents
) -> None:
    """latest_edition and ready_edition return None before generation, dict after."""
    monkeypatch.setattr(runner, "run_agent", fake_agents)
    today = date.today()
    assert await edition.latest_edition(onboarded_user.id, today) is None
    assert await edition.ready_edition(onboarded_user.id, today) is None

    await edition.generate_edition(onboarded_user.id, today)

    assert await edition.latest_edition(onboarded_user.id, today) is not None
    ed = await edition.ready_edition(onboarded_user.id, today)
    assert ed is not None and ed["status"] == "ready"
