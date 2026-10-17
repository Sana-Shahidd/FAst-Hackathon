"""Paper routes (docs/05_ROUTES.md): printing screen, status polling, the web edition."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app import deps
from app.deps import CurrentUser
from app.services import edition, i18n, pdf, reading

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


async def _edition_page(request: Request, user: CurrentUser, profile, day: date):
    """Render `edition.html` for one ready edition of this reader, or None when there is none."""
    ed = await edition.ready_edition(user.id, day)
    if ed is None:
        return None
    view = await reading.load_view(user.id, ed)
    return deps.render(
        request,
        "edition.html",
        lang=ed["lang"],
        profile=profile,
        ed=ed,
        day=day,
        reader_name=profile.display_name,
        nav_active="home"
        if day == edition.local_date_for(profile.timezone)
        else "archive",
        long_date=i18n.full_date(day, ed["lang"]),
        printed=reading.printed_time(ed.get("ready_at"), profile.timezone),
        **view,
    )


@router.get("/paper/today")
async def paper_today(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    profile, today = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    page = await _edition_page(request, user, profile, today)
    return page or RedirectResponse("/paper/generate", status_code=303)


@router.get("/paper/{day}")
async def paper_day(
    request: Request,
    day: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
):
    try:
        wanted = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=404) from None
    profile, _ = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    page = await _edition_page(request, user, profile, wanted)
    if page is None:
        raise HTTPException(status_code=404)
    return page


async def _own_ready_edition(user: CurrentUser, day: str) -> dict | None:
    """The reader's ready edition for `day`; None means "send them to onboarding"."""
    try:
        wanted = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=404) from None
    profile, _ = await _today(user)
    if profile is None:
        return None
    ed = await edition.ready_edition(user.id, wanted)
    if ed is None:
        raise HTTPException(status_code=404)
    return ed


@router.get("/paper/{day}/print")
async def paper_print(
    request: Request,
    day: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
):
    """Paper view: the exact HTML the PDF is printed from."""
    ed = await _own_ready_edition(user, day)
    if ed is None:
        return RedirectResponse("/onboarding", status_code=303)
    context = await pdf.build_context(ed, pdf=False)
    return deps.templates.TemplateResponse(request, "edition_print.html", context)


@router.get("/paper/{day}/pdf")
async def paper_pdf(
    request: Request,
    day: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
):
    """Download the A3 broadsheet PDF (printed on first request, then cached)."""
    ed = await _own_ready_edition(user, day)
    if ed is None:
        return RedirectResponse("/onboarding", status_code=303)
    try:
        data = await pdf.get_or_render_pdf(ed["id"])
    except pdf.PdfUnavailable:
        return deps.render(
            request, "error.html", 503, lang=ed["lang"], message_key="paper.pdf_busy"
        )
    await reading.record_signal(user.id, None, "pdf")
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf.filename_for(ed["edition_date"])}"'
        },
    )
