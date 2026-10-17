"""Reading routes (docs/05_ROUTES.md): the article sheet and the save toggle (F-07, F-19, F-22)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app import deps
from app.deps import CurrentUser
from app.services import reading

router = APIRouter()


async def _owned_or_404(user: CurrentUser, edition_article_id: str) -> dict:
    art = await reading.owned_article(user.id, edition_article_id)
    if art is None:
        raise HTTPException(status_code=404)
    return art


async def _sheet(request: Request, user: CurrentUser, art: dict):
    """The detail sheet, plus the card and progress line re-rendered out of band."""
    art = await reading.card_state(user.id, art)
    read, total = await reading.progress(user.id, art["edition_id"])
    return deps.render(
        request,
        "_article_sheet.html",
        lang=art["editions"]["lang"],
        art=art,
        read_count=read,
        total=total,
    )


@router.get("/paper/{day}/a/{edition_article_id}")
async def article_sheet(
    request: Request,
    day: str,
    edition_article_id: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
):
    """Bottom sheet with the full story; opening it marks the story as read (F-22)."""
    art = await _owned_or_404(user, edition_article_id)
    await reading.record_signal(user.id, edition_article_id, "open", once=True)
    return await _sheet(request, user, art)


@router.post("/saved/{edition_article_id}", dependencies=[Depends(deps.verify_csrf)])
async def toggle_saved(
    request: Request,
    edition_article_id: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    ctx: Annotated[str, Form()] = "card",
):
    """Save / unsave a story (F-19); returns the card, or the sheet when tapped there."""
    art = await _owned_or_404(user, edition_article_id)
    await reading.toggle_saved(user.id, edition_article_id)
    if ctx == "sheet":
        return await _sheet(request, user, art)
    art = await reading.card_state(user.id, art)
    return deps.render(
        request, "_article.html", lang=art["editions"]["lang"], art=art, oob=False
    )
