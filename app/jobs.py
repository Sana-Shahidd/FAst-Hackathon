"""Scheduled jobs (docs/02_PRD.md F-06): print each reader's paper at their delivery time, nightly upkeep.

`run_due_editions` is a plain coroutine so tests call it directly; APScheduler only decides when.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from app import deps
from app.services import edition, learning

logger = logging.getLogger(__name__)

CHECK_EVERY_MINUTES = 10
NIGHTLY_HOUR_UTC = 3


def is_due(now_utc: datetime, timezone: str, delivery: time, has_edition: bool) -> bool:
    """True when the reader's local clock has passed their delivery time and no paper exists yet."""
    if has_edition:
        return False
    try:
        local = now_utc.astimezone(ZoneInfo(timezone))
    except Exception:  # noqa: BLE001 - an unknown zone counts as UTC
        local = now_utc.astimezone(UTC)
    return local.time() >= delivery


def _delivery(value: object) -> time:
    text = str(value or "06:00")[:5]
    hours, _, minutes = text.partition(":")
    return time(int(hours), int(minutes or 0))


async def run_due_editions(
    now: datetime | None = None, only: set[str] | None = None
) -> int:
    """Start printing for every onboarded reader whose paper is due (`only` limits it to those user ids); returns how many were started."""
    now = now or datetime.now(UTC)
    client = deps.supabase_admin()
    readers = await asyncio.to_thread(
        lambda: (
            client.table("profiles")
            .select("user_id,timezone,delivery_time")
            .not_.is_("onboarded_at", "null")
            .execute()
            .data
        )
    )
    started = 0
    for reader in readers:
        if only is not None and reader["user_id"] not in only:
            continue
        today = edition.local_date_for(reader["timezone"], now)
        latest = await edition.latest_edition(reader["user_id"], today)
        if latest is not None and latest["status"] != "failed":
            continue
        if is_due(now, reader["timezone"], _delivery(reader["delivery_time"]), False):
            await edition.start_generation(reader["user_id"], today)
            started += 1
    return started


async def nightly() -> None:
    """Quiet-reader upkeep for everyone (ignored stories, long-low interests)."""
    result = await learning.nightly_decay()
    logger.info("nightly upkeep: %s", result)


async def _safe(job) -> None:
    try:
        await job()
    except Exception:
        logger.exception("scheduled job %s failed", getattr(job, "__name__", job))


def start_scheduler():
    """Start the in-process scheduler (the app lifespan calls this); returns it so it can be stopped."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _safe,
        "interval",
        args=[run_due_editions],
        minutes=CHECK_EVERY_MINUTES,
        id="due-editions",
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _safe,
        "cron",
        args=[nightly],
        hour=NIGHTLY_HOUR_UTC,
        id="nightly",
        max_instances=1,
    )
    scheduler.start()
    return scheduler
