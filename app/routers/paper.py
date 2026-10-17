"""Paper routes (docs/05_ROUTES.md): printing screen, status polling, the web edition, Paper view, PDF."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app import deps
from app.config import settings
from app.deps import CurrentUser
from app.services import edition, i18n, pdf, puzzle, reading

router = APIRouter()


def dev_enabled() -> bool:
    """Demo helpers (time travel) exist in dev and in CI's `test`, never in production."""
    return settings.APP_ENV in ("dev", "test")


async def _today(user: CurrentUser):
    """(profile, reader's local date); profile is None until onboarding is finished."""
    return await edition.profile_today(user.id)


def _run_day(day: str | None, today: date) -> date:
    """The date a printing page is about: `?day=` only exists for dev time travel."""
    if day and dev_enabled():
        try:
            return date.fromisoformat(day)
        except ValueError:
            return today
    return today


def _paper_url(target: date, today: date) -> str:
    return "/paper/today" if target == today else f"/paper/{target.isoformat()}"


def _status_url(target: date, today: date) -> str:
    return (
        "/paper/status"
        if target == today
        else f"/paper/status?day={target.isoformat()}"
    )


@router.get("/paper/generate")
async def generate_page(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    day: str | None = None,
):
    """Start printing (once) and show the live progress page."""
    profile, today = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    target = _run_day(day, today)
    latest = await edition.latest_edition(user.id, target)
    if latest is None:
        await edition.start_generation(user.id, target)
    elif latest["status"] == "ready" and not edition.regenerating(user.id, latest):
        return RedirectResponse(_paper_url(target, today), status_code=303)
    return deps.render(
        request,
        "generating.html",
        profile=profile,
        status_url=_status_url(target, today),
    )


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
    await edition.start_generation(user.id, today, regenerate=regenerate == "1")
    return RedirectResponse("/paper/generate", status_code=303)


@router.post("/dev/time-travel", dependencies=[Depends(deps.verify_csrf)])
async def time_travel(user: Annotated[CurrentUser, Depends(deps.require_user)]):
    """Dev only: print the paper for the day after the reader's newest edition (demo learning)."""
    if not dev_enabled():
        raise HTTPException(status_code=404)
    profile, today = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    rows = await edition.list_editions(user.id)
    newest = max((date.fromisoformat(r["edition_date"]) for r in rows), default=today)
    target = max(newest, today) + timedelta(days=1)
    await edition.start_generation(user.id, target)
    return RedirectResponse(
        f"/paper/generate?day={target.isoformat()}", status_code=303
    )


@router.get("/paper/status")
async def status(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    day: str | None = None,
):
    """HTMX fragment polled by the printing page: live steps; `ready` redirects to the paper."""
    profile, today = await _today(user)
    target = _run_day(day, today) if profile else None
    latest = await edition.latest_edition(user.id, target) if profile else None
    state = latest["status"] if latest else "waiting"
    steps: list[dict] = []
    if edition.regenerating(user.id, latest):
        state = "generating"  # the new version's row is not created yet
    elif latest:
        steps = await edition.steps_for(latest["id"])
    # htmx stops polling on 286, which is what a finished (failed) run wants.
    response = deps.render(
        request,
        "_status.html",
        286 if state == "failed" else 200,
        state=state,
        steps=steps,
    )
    if state == "ready":
        response.headers["HX-Redirect"] = _paper_url(target, today)
    return response


async def _edition_page(
    request: Request,
    user: CurrentUser,
    profile,
    day: date,
    version: int | None = None,
):
    """Render `edition.html` for one ready edition of this reader, or None when there is none."""
    ed = await edition.ready_edition(user.id, day, version)
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
        vq=_version_query(ed),
        puzzle_card=await puzzle.card_state(user.id, ed["id"]),
        dev=dev_enabled(),
        reader_name=profile.display_name,
        nav_active="home"
        if day == edition.local_date_for(profile.timezone)
        else "archive",
        long_date=i18n.full_date(day, ed["lang"]),
        printed=reading.printed_time(ed.get("ready_at"), profile.timezone),
        **view,
    )


def _version_query(ed: dict) -> str:
    """`?v=N` for an older version, so Paper view / PDF links stay on the version being read."""
    return f"?v={ed['version']}" if ed["status"] == "superseded" else ""


@router.get("/paper/today")
async def paper_today(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    profile, today = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    page = await _edition_page(request, user, profile, today)
    return page or RedirectResponse("/paper/generate", status_code=303)


def _parse_day(day: str) -> date:
    try:
        return date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=404) from None


@router.get("/paper/{day}")
async def paper_day(
    request: Request,
    day: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    v: int | None = None,
):
    """A past (or future, in dev) edition; `?v=` picks an older version of that date."""
    wanted = _parse_day(day)
    profile, _ = await _today(user)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    page = await _edition_page(request, user, profile, wanted, v)
    if page is None:
        raise HTTPException(status_code=404)
    return page


async def _own_ready_edition(
    user: CurrentUser, day: str, version: int | None = None
) -> dict | None:
    """The reader's ready edition for `day`; None means "send them to onboarding"."""
    wanted = _parse_day(day)
    profile, _ = await _today(user)
    if profile is None:
        return None
    ed = await edition.ready_edition(user.id, wanted, version)
    if ed is None:
        raise HTTPException(status_code=404)
    return ed


@router.get("/paper/{day}/print")
async def paper_print(
    request: Request,
    day: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    v: int | None = None,
):
    """Paper view: the exact HTML the PDF is printed from."""
    ed = await _own_ready_edition(user, day, v)
    if ed is None:
        return RedirectResponse("/onboarding", status_code=303)
    context = await pdf.build_context(ed, pdf=False)
    return deps.templates.TemplateResponse(request, "edition_print.html", context)


@router.get("/paper/{day}/pdf")
async def paper_pdf(
    request: Request,
    day: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    v: int | None = None,
):
    """Download the A3 broadsheet PDF (printed on first request, then cached)."""
    ed = await _own_ready_edition(user, day, v)
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
