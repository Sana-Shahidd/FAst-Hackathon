"""Paper routes (docs/05_ROUTES.md): printing screen, status polling, today's paper.

`/paper/today` renders the edition in T-07; until then it only checks the reader has one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import deps
from app.deps import CurrentUser
from app.services import edition

router = APIRouter()


async def _today(user: CurrentUser):
    """(profile, reader's local date); profile is None until onboarding is finished."""
    profile = await edition.get_profile(user.id)
    if profile is None or not await edition.is_onboarded(user.id):
        return None, None
    return profile, edition.local_date_for(profile.timezone)


@router.get("/paper/generate")
async def generate_page(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """Start printing (once) and show the live progress page."""
    profile, today = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    latest = await edition.latest_edition(user.id, today)
    if latest is None:
        edition.start_generation(user.id, today)
    elif latest["status"] == "ready":
        return RedirectResponse("/paper/today", status_code=303)
    return deps.render(request, "generating.html", profile=profile)


@router.post("/paper/generate", dependencies=[Depends(deps.verify_csrf)])
@deps.limiter.limit("3/10 minutes", key_func=deps.user_key)
async def regenerate(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    regenerate: Annotated[str, Form()] = "",
):
    """`regenerate=1` prints a new version (the old one stays in the archive)."""
    profile, today = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    edition.start_generation(user.id, today, regenerate=regenerate == "1")
    return RedirectResponse("/paper/generate", status_code=303)


@router.get("/paper/status")
async def status(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """HTMX fragment polled by the printing page: live steps; `ready` redirects to the paper."""
    profile, today = await _today(user)
    latest = await edition.latest_edition(user.id, today) if profile else None
    state = latest["status"] if latest else "waiting"
    steps = await edition.steps_for(latest["id"]) if latest else []
    # htmx stops polling on 286, which is what a finished (failed) run wants.
    response = deps.render(
        request,
        "_status.html",
        286 if state == "failed" else 200,
        state=state,
        steps=steps,
    )
    if state == "ready":
        response.headers["HX-Redirect"] = "/paper/today"
    return response


@router.get("/paper/today")
async def paper_today(user: Annotated[CurrentUser, Depends(deps.require_user)]):
    profile, today = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    if await edition.ready_edition(user.id, today) is None:
        return RedirectResponse("/paper/generate", status_code=303)
    raise NotImplementedError("F-07: today's edition page arrives with T-07")
