"""Integration tests for `GET /health` (docs/05_ROUTES.md)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_health_returns_ok_version_db_and_pdf(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ok", "version", "db", "pdf"}
    assert body["ok"] is True
    assert isinstance(body["version"], str) and body["version"]
    assert isinstance(body["db"], bool)
    assert isinstance(body["pdf"], bool)


def test_health_version_is_the_commit_sha(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_SHA", "1a2b3c4")
    assert client.get("/health").json()["version"] == "1a2b3c4"


def test_health_version_falls_back_to_render_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_SHA", "dev")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "9f8e7d6")
    assert client.get("/health").json()["version"] == "9f8e7d6"
