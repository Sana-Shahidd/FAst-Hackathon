"""Shared dependencies. T-02 adds the Supabase service-role client; T-04 adds sessions."""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from supabase import Client, create_client


@lru_cache(maxsize=1)
def supabase_admin() -> Client:
    """Service-role Supabase client. Server-side only; the key never reaches the browser."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
