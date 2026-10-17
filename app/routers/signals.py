"""Reader signals (docs/05_ROUTES.md): the click-through redirect and `POST /signals`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app import deps
from app.deps import CurrentUser
from app.services import reading

router = APIRouter()


@router.get("/r/{edition_article_id}")
async def redirect_to_original(
    edition_article_id: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
):
    """Log the click, then 302 to the URL stored with the story (never one from the query)."""
    art = await reading.owned_article(user.id, edition_article_id)
    if art is None:
        raise HTTPException(status_code=404)
    await reading.record_signal(user.id, edition_article_id, "click")
    return RedirectResponse(art["articles"]["url"], status_code=302)


@router.post("/signals", dependencies=[Depends(deps.verify_csrf)])
async def post_signal(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    edition_article_id: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    value: Annotated[float | None, Form()] = None,
):
    """`more_like`/`less_like` re-render the card, `skip_source` removes it, `dwell` is a beacon."""
    if kind not in reading.SIGNAL_KINDS:
        raise HTTPException(status_code=422, detail="unknown signal kind")
    art = await reading.owned_article(user.id, edition_article_id)
    if art is None:
        raise HTTPException(status_code=404)
    if kind == "dwell":
        seconds = min(max(value or 0.0, 0.0), reading.MAX_DWELL_SECONDS)
        await reading.record_signal(user.id, edition_article_id, kind, seconds)
        return Response(status_code=204)
    await reading.record_signal(user.id, edition_article_id, kind, once=True)
    if kind == "skip_source":
        return Response(status_code=200)
    art = await reading.card_state(user.id, art)
    return deps.render(
        request, "_article.html", lang=art["editions"]["lang"], art=art, oob=False
    )
