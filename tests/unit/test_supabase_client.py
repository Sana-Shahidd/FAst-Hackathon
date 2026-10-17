"""The shared service-role client must be safe to use from many threads (found by a failing gate run)."""

from __future__ import annotations

import httpx
import pytest

from app import deps

pytestmark = pytest.mark.unit


def test_the_shared_connection_is_http1_with_a_pool_not_one_http2_stream_set() -> None:
    client = deps.threadsafe_http()
    try:
        pool = client._transport._pool  # httpcore connection pool
        assert pool._http2 is False and pool._http1 is True
        assert pool._max_connections == 32
        assert client.follow_redirects is True
    finally:
        client.close()


def test_the_admin_client_is_built_on_that_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict = {}

    def fake_create(url, key, options=None):
        seen["options"] = options
        return object()

    monkeypatch.setattr(deps, "create_client", fake_create)
    monkeypatch.setattr(deps.settings, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(deps.settings, "SUPABASE_SERVICE_ROLE_KEY", "service")
    deps.supabase_admin.cache_clear()
    try:
        deps.supabase_admin()
    finally:
        deps.supabase_admin.cache_clear()
    assert isinstance(seen["options"].httpx_client, httpx.Client)
    assert seen["options"].httpx_client._transport._pool._http2 is False
