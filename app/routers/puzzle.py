"""The headline puzzle (docs/05_ROUTES.md, F-17): one question at a time, graded on the server."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import deps
from app.deps import CurrentUser
from app.services import edition, i18n, puzzle

router = APIRouter()


async def _context(user: CurrentUser, day: str):
    """(profile, edition, today) for a puzzle page; a None profile means "finish onboarding"."""
    profile, today = await edition.profile_today(user.id)
    if profile is None:
        return None, None, None
    try:
        wanted = today if day == "today" else date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=404) from None
    ed = await edition.ready_edition(user.id, wanted)
    if ed is None:
        raise HTTPException(status_code=404)
    return profile, ed, today


async def _body(
    request: Request,
    user: CurrentUser,
    profile,
    ed: dict,
    today: date,
    template: str,
    revealed: dict | None = None,
):
    items = await puzzle.get_items(ed["id"])
    if not items:
        raise HTTPException(status_code=404)
    answers = await puzzle.get_attempt(user.id, ed["id"])
    summary = puzzle.summarize(answers, len(items))
    current = revealed["q"] if revealed else summary["next_q"]
    chosen = next((a for a in answers if revealed and a["q"] == revealed["q"]), None)
    edition_day = date.fromisoformat(ed["edition_date"])
    return deps.render(
        request,
        template,
        lang=ed["lang"],
        profile=profile,
        day="today" if edition_day == today else ed["edition_date"],
        items=items,
        total=len(items),
        summary=summary,
        current=current,
        item=items[current] if current is not None else None,
        parts=puzzle.split_blank(items[current]) if current is not None else None,
        chosen=chosen,
        revealed=revealed,
        stories=[
            {"id": i["edition_article_id"], "headline": puzzle.restore(i)}
            for i in items
        ],
        streak=await puzzle.streak(user.id, today),
        long_date=i18n.full_date(edition_day, ed["lang"]),
        nav_active="home",
    )


@router.get("/puzzle/{day}")
async def puzzle_page(
    request: Request, day: str, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """The puzzle page; HTMX asks for just the body (the next question or the final score)."""
    profile, ed, today = await _context(user, day)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    template = (
        "_puzzle_body.html" if request.headers.get("HX-Request") else "puzzle.html"
    )
    return await _body(request, user, profile, ed, today, template)


@router.post("/puzzle/{day}/answer", dependencies=[Depends(deps.verify_csrf)])
async def puzzle_answer(
    request: Request,
    day: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    q: Annotated[int, Form()],
    choice: Annotated[str, Form()],
):
    """Grade one answer (idempotent per question) and show the reveal card."""
    profile, ed, today = await _context(user, day)
    if profile is None:
        raise HTTPException(status_code=404)
    try:
        result = await puzzle.grade(user.id, ed["id"], q, choice)
    except LookupError:
        raise HTTPException(status_code=404) from None
    except ValueError:
        raise HTTPException(status_code=422, detail="bad question or choice") from None
    return await _body(
        request, user, profile, ed, today, "_puzzle_body.html", {"q": q, **result}
    )
