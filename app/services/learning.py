"""Learning (docs/02_PRD.md F-10, F-11): reader signals move interest weights, the Learner suggests more.

Every weight change is written to `interest_history`, so the profile page can show it evolving.
All queries filter by `user_id` (AGENTS.md Rule 3). The synchronous Supabase client is used one
query at a time, never in parallel.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from app import deps
from app.agents import learner
from app.agents.learner import Evidence
from app.config import (
    LEARNER_MIN_SIGNALS,
    WEIGHT_CLICK,
    WEIGHT_DWELL,
    WEIGHT_IGNORED,
    WEIGHT_LESS,
    WEIGHT_MAX,
    WEIGHT_MIN,
    WEIGHT_MORE,
    WEIGHT_PUZZLE,
    WEIGHT_SAVE,
)
from app.services import activity

logger = logging.getLogger(__name__)

SIGNAL_WEIGHT = {
    "click": WEIGHT_CLICK,
    "more_like": WEIGHT_MORE,
    "less_like": WEIGHT_LESS,
    "dwell": WEIGHT_DWELL,
    "save": WEIGHT_SAVE,
    "puzzle_correct": WEIGHT_PUZZLE,
    "impression_no_click": WEIGHT_IGNORED,
}
HISTORY_REASON = {"impression_no_click": "ignored"}
DWELL_MIN_SECONDS = 20
LOW_WEIGHT = 0.1  # below this for LOW_DAYS days an interest becomes inactive
LOW_DAYS = 7
LEARNER_KINDS = ("click", "more_like", "less_like", "save", "skip_source")
POSITIVE_KINDS = ("click", "more_like", "save")
LEARNER_LOWER_STEP = -0.1
ACCEPTED_WEIGHT = 0.5
ADDED_WEIGHT = 0.6
IGNORED_AFTER_DAYS = 2
IGNORED_WINDOW_DAYS = 9


async def _db(fn):
    return await asyncio.to_thread(fn)


async def _insert(client, table: str, row: dict) -> None:
    await _db(lambda: client.table(table).insert(row).execute())


# --------------------------------------------------------------- pure helpers


def delta_for(kind: str, value: float | None = None) -> float:
    """Weight change for one signal; a dwell only counts after 20 seconds."""
    if kind == "dwell" and (value or 0) < DWELL_MIN_SECONDS:
        return 0.0
    return SIGNAL_WEIGHT.get(kind, 0.0)


def clamp(weight: float) -> float:
    return round(min(WEIGHT_MAX, max(WEIGHT_MIN, weight)), 2)


def low_since_after(
    new_weight: float, low_since: str | None, now: datetime
) -> str | None:
    """`low_since` starts when the weight drops under 0.1 and resets when it recovers."""
    if new_weight < LOW_WEIGHT:
        return low_since or now.isoformat()
    return None


def long_low(low_since: str | None, now: datetime) -> bool:
    """True when an interest has stayed below 0.1 for 7 days."""
    if not low_since:
        return False
    return now - datetime.fromisoformat(low_since) >= timedelta(days=LOW_DAYS)


def sparkline_points(values: list[float], width: int = 90, height: int = 26) -> str:
    """SVG `points` for a tiny trend line of weights between 0 and 1 (a flat line for one value)."""
    if not values:
        return ""
    if len(values) == 1:
        values = [values[0], values[0]]
    step = width / (len(values) - 1)
    return " ".join(
        f"{i * step:.1f},{(height - 2) - min(1.0, max(0.0, v)) * (height - 4):.1f}"
        for i, v in enumerate(values)
    )


def history_series(current: float, rows: list[dict]) -> list[float]:
    """Weights over time for one interest: where it started, then every change."""
    if not rows:
        return [current]
    ordered = sorted(rows, key=lambda r: r["created_at"])
    return [float(ordered[0]["old_weight"]), *(float(r["new_weight"]) for r in ordered)]


# -------------------------------------------------------------------- weights


async def adjust_interest(
    user_id: str, interest: dict, delta: float, reason: str
) -> float | None:
    """Move one interest by `delta` (clamped); returns the new weight, or None when nothing changed."""
    old = float(interest["weight"])
    new = clamp(old + delta)
    if new == old:
        return None
    client = deps.supabase_admin()
    now = datetime.now(UTC)
    await _db(
        lambda: (
            client.table("interests")
            .update(
                {
                    "weight": new,
                    "low_since": low_since_after(new, interest.get("low_since"), now),
                }
            )
            .eq("id", interest["id"])
            .eq("user_id", user_id)
            .execute()
        )
    )
    await _db(
        lambda: (
            client.table("interest_history")
            .insert(
                {
                    "interest_id": interest["id"],
                    "old_weight": old,
                    "new_weight": new,
                    "reason": HISTORY_REASON.get(reason, reason),
                }
            )
            .execute()
        )
    )
    return new


async def _story(user_id: str, edition_article_id: str) -> dict | None:
    """The reader's own edition article with its interest, topic and source."""
    client = deps.supabase_admin()
    try:
        rows = await _db(
            lambda: (
                client.table("edition_articles")
                .select(
                    "interest_id,topic_key,articles(source_name),editions!inner(user_id)"
                )
                .eq("id", edition_article_id)
                .eq("editions.user_id", user_id)
                .limit(1)
                .execute()
                .data
            )
        )
    except Exception:  # noqa: BLE001 - an unknown id simply has no effect
        return None
    return rows[0] if rows else None


async def _interest_of(user_id: str, story: dict) -> dict | None:
    client = deps.supabase_admin()
    query = (
        client.table("interests")
        .select("id,weight,low_since,active")
        .eq("user_id", user_id)
        .eq("active", True)
    )
    if story.get("interest_id"):
        query = query.eq("id", story["interest_id"])
    elif story.get("topic_key"):
        query = query.eq("topic_key", story["topic_key"])
    else:
        return None
    rows = await _db(lambda: query.limit(1).execute().data)
    return rows[0] if rows else None


async def apply_signal(
    user_id: str, edition_article_id: str | None, kind: str, value: float | None = None
) -> None:
    """Turn one reader signal into a weight change (or a blocked source) on the story's interest."""
    if not edition_article_id:
        return
    story = await _story(user_id, edition_article_id)
    if story is None:
        return
    if kind == "skip_source":
        source = (story.get("articles") or {}).get("source_name")
        if source:
            client = deps.supabase_admin()
            row = {"user_id": user_id, "source_name": source}
            await _db(
                lambda: (
                    client.table("blocked_sources")
                    .upsert(row, on_conflict="user_id,source_name")
                    .execute()
                )
            )
        return
    delta = delta_for(kind, value)
    if not delta:
        return
    interest = await _interest_of(user_id, story)
    if interest:
        await adjust_interest(user_id, interest, delta, kind)


# --------------------------------------------------------- interests (profile)


async def list_interests(user_id: str) -> list[dict]:
    """Active interests with their weight history series, strongest first."""
    client = deps.supabase_admin()
    interests = await _db(
        lambda: (
            client.table("interests")
            .select("id,label,topic_key,query,weight,source")
            .eq("user_id", user_id)
            .eq("active", True)
            .order("weight", desc=True)
            .execute()
            .data
        )
    )
    if not interests:
        return []
    ids = [i["id"] for i in interests]
    history = await _db(
        lambda: (
            client.table("interest_history")
            .select("interest_id,old_weight,new_weight,created_at")
            .in_("interest_id", ids)
            .execute()
            .data
        )
    )
    by_interest: dict[str, list[dict]] = {}
    for row in history:
        by_interest.setdefault(row["interest_id"], []).append(row)
    for interest in interests:
        series = history_series(
            float(interest["weight"]), by_interest.get(interest["id"], [])
        )
        interest["series"] = series
        interest["spark"] = sparkline_points(series)
        interest["percent"] = round(float(interest["weight"]) * 100)
    return interests


async def set_weight(user_id: str, interest_id: str, weight: float) -> bool:
    """The reader sets an interest to an exact weight (history reason `manual`)."""
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("interests")
            .select("id,weight,low_since,active")
            .eq("id", interest_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
        )
    )
    if not rows:
        return False
    await adjust_interest(
        user_id, rows[0], clamp(weight) - float(rows[0]["weight"]), "manual"
    )
    return True


async def remove_interest(user_id: str, interest_id: str) -> bool:
    client = deps.supabase_admin()
    done = await _db(
        lambda: (
            client.table("interests")
            .delete()
            .eq("id", interest_id)
            .eq("user_id", user_id)
            .execute()
            .data
        )
    )
    return bool(done)


async def add_interest(
    user_id: str,
    label: str,
    query: str | None = None,
    *,
    source: str = "custom",
    weight: float = ADDED_WEIGHT,
) -> bool:
    """Add (or reactivate) an interest; `query` defaults to the quoted label."""
    label = " ".join(label.split())[:60]
    if len(label) < 2:
        return False
    row = {
        "user_id": user_id,
        "label": label,
        "query": (query or f'"{label}"')[:200],
        "weight": clamp(weight),
        "source": source,
        "active": True,
        "low_since": None,
    }
    client = deps.supabase_admin()
    await _db(
        lambda: (
            client.table("interests").upsert(row, on_conflict="user_id,label").execute()
        )
    )
    return True


# ---------------------------------------------------------------- suggestions


async def pending_suggestions(user_id: str) -> list[dict]:
    client = deps.supabase_admin()
    return await _db(
        lambda: (
            client.table("suggestions")
            .select("id,label,query,reason")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .order("created_at")
            .execute()
            .data
        )
    )


async def decide_suggestion(user_id: str, suggestion_id: str, accept: bool) -> bool:
    """Yes adds the interest (weight 0.5, source `learned`); No remembers the refusal. False if not found."""
    client = deps.supabase_admin()
    try:
        rows = await _db(
            lambda: (
                client.table("suggestions")
                .select("id,label,query,status")
                .eq("id", suggestion_id)
                .eq("user_id", user_id)
                .eq("status", "pending")
                .limit(1)
                .execute()
                .data
            )
        )
    except Exception:  # noqa: BLE001 - a malformed id is simply "not found"
        return False
    if not rows:
        return False
    if accept:
        await add_interest(
            user_id,
            rows[0]["label"],
            rows[0]["query"],
            source="learned",
            weight=ACCEPTED_WEIGHT,
        )
    status = "accepted" if accept else "rejected"
    await _db(
        lambda: (
            client.table("suggestions")
            .update({"status": status})
            .eq("id", suggestion_id)
            .eq("user_id", user_id)
            .execute()
        )
    )
    return True


async def recent_notes(user_id: str, limit: int = 3) -> list[str]:
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("learner_notes")
            .select("note")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )
    )
    return [r["note"] for r in rows]


# -------------------------------------------------------------------- Learner


async def _evidence(
    client, user_id: str, rows: list[dict]
) -> tuple[list[Evidence], list[Evidence]]:
    ids = list({r["edition_article_id"] for r in rows if r["edition_article_id"]})
    stories = await _db(
        lambda: (
            client.table("edition_articles")
            .select("id,headline,topic_key")
            .in_("id", ids)
            .execute()
            .data
        )
    )
    by_id = {s["id"]: s for s in stories}
    liked: list[Evidence] = []
    disliked: list[Evidence] = []
    for row in rows:  # newest first
        story = by_id.get(row["edition_article_id"])
        if not story:
            continue
        item = Evidence(story["headline"], story.get("topic_key"))
        if row["kind"] in POSITIVE_KINDS:
            liked.append(item)
        elif row["kind"] == "less_like":
            disliked.append(item)
    return liked, disliked


async def maybe_run_learner(user_id: str, edition_id: str | None = None) -> bool:
    """Run the Learner once the reader has given at least 5 unprocessed signals; True when it ran."""
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("signals")
            .select("id,kind,edition_article_id")
            .eq("user_id", user_id)
            .eq("processed_by_learner", False)
            .in_("kind", list(LEARNER_KINDS))
            .order("created_at", desc=True)
            .limit(200)
            .execute()
            .data
        )
    )
    if len(rows) < LEARNER_MIN_SIGNALS:
        return False
    liked, disliked = await _evidence(client, user_id, rows)
    interests = await _db(
        lambda: (
            client.table("interests")
            .select("id,label,topic_key,weight,low_since,active")
            .eq("user_id", user_id)
            .eq("active", True)
            .execute()
            .data
        )
    )
    profile = await _db(
        lambda: (
            client.table("profiles")
            .select("edition_lang")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
        )
    )
    lang = profile[0]["edition_lang"] if profile else "en"
    known = await _db(
        lambda: (
            client.table("suggestions")
            .select("label")
            .eq("user_id", user_id)
            .execute()
            .data
        )
    )
    known_labels = {r["label"].lower() for r in known}
    out, used_fallback = await learner.suggest(
        [(i["label"], float(i["weight"]), i["topic_key"]) for i in interests],
        liked,
        disliked,
        known_labels,
        lang,
        edition_id,
    )
    await _apply_learner(client, user_id, out, interests, len(liked))
    done_ids = [r["id"] for r in rows]
    await _db(
        lambda: (
            client.table("signals")
            .update({"processed_by_learner": True})
            .in_("id", done_ids)
            .execute()
        )
    )
    summary = (
        f"Suggests {', '.join(repr(a.label) for a in out.add)}"
        if out.add
        else "No new interests suggested"
    )
    await activity.log(
        edition_id,
        "learner",
        "fallback" if used_fallback else "decision",
        f"{summary} ({len(rows)} signals)",
        {"add": [a.label for a in out.add], "lower": out.lower},
    )
    return True


async def _apply_learner(
    client, user_id: str, out, interests: list[dict], liked_count: int
) -> None:
    if out.add:
        rows = [
            {
                "user_id": user_id,
                "label": item.label,
                "query": item.query,
                "reason": f"{liked_count} stories you read, saved or liked",
                "status": "pending",
            }
            for item in out.add
        ]
        await _db(
            lambda: (
                client.table("suggestions")
                .upsert(rows, on_conflict="user_id,label", ignore_duplicates=True)
                .execute()
            )
        )
    by_label = {i["label"].lower(): i for i in interests}
    for label in out.lower:
        interest = by_label.get(label.lower())
        if interest:
            await adjust_interest(user_id, interest, LEARNER_LOWER_STEP, "learner")
    if out.note:
        row = {"user_id": user_id, "note": out.note}
        await _db(lambda: client.table("learner_notes").insert(row).execute())


# ----------------------------------------------------------------- nightly job


async def nightly_decay(
    user_id: str | None = None, today: date | None = None
) -> dict[str, int]:
    """Quiet-reader upkeep: ignored stories nudge weights down; long-low interests become inactive."""
    client = deps.supabase_admin()
    now = datetime.now(UTC)
    today = today or now.date()
    query = client.table("editions").select("id,user_id").eq("status", "ready")
    query = query.lte(
        "edition_date", (today - timedelta(days=IGNORED_AFTER_DAYS)).isoformat()
    )
    query = query.gte(
        "edition_date", (today - timedelta(days=IGNORED_WINDOW_DAYS)).isoformat()
    )
    if user_id:
        query = query.eq("user_id", user_id)
    editions = await _db(lambda: query.execute().data)
    ignored = 0
    for edition in editions:
        ignored += await _ignore_unread(client, edition["user_id"], edition["id"])
    deactivated = await _deactivate_low(client, user_id, now)
    return {"ignored": ignored, "deactivated": deactivated}


async def _ignore_unread(client, user_id: str, edition_id: str) -> int:
    stories = await _db(
        lambda: (
            client.table("edition_articles")
            .select("id")
            .eq("edition_id", edition_id)
            .execute()
            .data
        )
    )
    ids = [s["id"] for s in stories]
    if not ids:
        return 0
    seen = await _db(
        lambda: (
            client.table("signals")
            .select("edition_article_id")
            .eq("user_id", user_id)
            .in_("kind", ["open", "click", "impression_no_click"])
            .in_("edition_article_id", ids)
            .execute()
            .data
        )
    )
    touched = {s["edition_article_id"] for s in seen}
    count = 0
    for story_id in ids:
        if story_id in touched:
            continue
        row = {
            "user_id": user_id,
            "edition_article_id": story_id,
            "kind": "impression_no_click",
        }
        await _insert(client, "signals", row)
        await apply_signal(user_id, story_id, "impression_no_click")
        count += 1
    return count


async def _deactivate_low(client, user_id: str | None, now: datetime) -> int:
    query = (
        client.table("interests")
        .select("id,low_since")
        .eq("active", True)
        .lt("weight", LOW_WEIGHT)
    )
    if user_id:
        query = query.eq("user_id", user_id)
    rows = await _db(lambda: query.execute().data)
    stale = [r["id"] for r in rows if long_low(r.get("low_since"), now)]
    if stale:
        await _db(
            lambda: (
                client.table("interests")
                .update({"active": False})
                .in_("id", stale)
                .execute()
            )
        )
    return len(stale)
