"""The archive (docs/05_ROUTES.md, F-09): every earlier paper, newest first."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app import deps
from app.deps import CurrentUser
from app.routers.paper import dev_enabled
from app.services import edition, i18n, reading

router = APIRouter()


@router.get("/archive")
async def archive(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """Mini front pages of all editions; older versions of a date are collapsed under it."""
    profile, _ = await edition.profile_today(user.id)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    lang = profile.edition_lang
    entries = reading.group_editions(await edition.list_editions(user.id))
    for entry in entries:
        entry["label"] = i18n.full_date(date.fromisoformat(entry["day"]), lang)
    return deps.render(
        request,
        "archive.html",
        lang=lang,
        profile=profile,
        entries=entries,
        lang_names={code: meta["native"] for code, meta in i18n.languages().items()},
        nav_active="archive",
        dev=dev_enabled(),
    )
