"""Writes `agent_activity` rows, shown on "How this paper was made" (docs/04_DATA.md)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import deps

logger = logging.getLogger(__name__)


async def log(
    edition_id: str | None,
    agent: str,
    kind: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Insert one activity row. Never raises: logging must not stop a paper."""
    row = {
        "edition_id": edition_id,
        "agent": agent,
        "kind": kind,
        "message": message[:300],
        "data": data or {},
    }
    try:
        client = deps.supabase_admin()
        await asyncio.to_thread(
            lambda: client.table("agent_activity").insert(row).execute()
        )
    except Exception as exc:  # noqa: BLE001 - best effort by design
        logger.warning(
            "agent_activity not written (%s): %s", type(exc).__name__, message
        )
