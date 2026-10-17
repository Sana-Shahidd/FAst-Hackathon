"""Users only see their own data (AGENTS.md Rule 3). Skeleton: grows with each router.

Per docs/09 §2 the finished file proves that user A gets 404 for user B's paper, PDF,
`/r/`, saved list and puzzle. Those routes arrive in T-07…T-11; each task adds its case
here. Today it proves the layers that already exist: the database itself, and sessions.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings

pytestmark = pytest.mark.integration


def rest_rows(table: str, token: str) -> list[dict]:
    """Read `table` the way browser JS would: PostgREST with the user's own JWT."""
    response = httpx.get(
        f"{settings.SUPABASE_URL}/rest/v1/{table}?select=*",
        headers={
            "apikey": settings.SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {token}",
        },
        timeout=20,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_user_cannot_read_any_profile_straight_from_the_database(
    make_user, admin
) -> None:
    a, b = make_user("Reader A"), make_user("Reader B")
    stored = {
        r["user_id"] for r in admin.table("profiles").select("user_id").execute().data
    }
    assert {a.id, b.id} <= stored  # both rows really exist for the server
    assert (
        rest_rows("profiles", a.access_token) == []
    )  # RLS: no policies, browser gets nothing
    assert rest_rows("profiles", b.access_token) == []


def test_user_data_tables_are_closed_to_a_users_own_token(make_user, admin) -> None:
    a = make_user()
    admin.table("interests").insert(
        {
            "user_id": a.id,
            "label": "AI",
            "topic_key": "ai",
            "query": "ai",
            "weight": 0.8,
        }
    ).execute()
    admin.table("muted_keywords").insert(
        {"user_id": a.id, "keyword": "crypto"}
    ).execute()
    for table in (
        "interests",
        "muted_keywords",
        "editions",
        "signals",
        "saved_articles",
    ):
        assert rest_rows(table, a.access_token) == [], table


def test_each_session_resolves_to_its_own_user_only(make_user) -> None:
    from app import deps

    a, b = make_user(), make_user()
    assert deps._user_from_token(a.access_token).id == a.id
    assert deps._user_from_token(b.access_token).id == b.id
    assert deps._user_from_token(a.access_token).id != b.id


def test_signed_out_visitors_cannot_reach_a_protected_page(client: TestClient) -> None:
    response = client.get("/paper/today", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/login")


def test_a_tampered_access_token_never_authenticates(make_user) -> None:
    """A forged or altered access cookie is not accepted as any user."""
    from app import deps

    a = make_user()
    tampered = a.access_token[:-4] + (
        "AAAA" if not a.access_token.endswith("AAAA") else "BBBB"
    )
    assert deps._user_from_token(tampered) is None
