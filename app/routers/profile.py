"""Reader preferences (docs/05_ROUTES.md): the profile page, interests, suggestions and reading comfort."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app import deps
from app.deps import CurrentUser
from app.services import edition, learning, prefs

router = APIRouter()

THEMES = ("day", "night", "auto")
TEXT_SIZES = ("S", "M", "L", "XL")


@router.post("/settings/comfort", dependencies=[Depends(deps.verify_csrf)])
async def save_comfort(
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    theme: Annotated[str | None, Form()] = None,
    text_size: Annotated[str | None, Form()] = None,
):
    """Save the reader's theme and/or text size (F-20); the page reloads to apply them."""
    changes: dict[str, str] = {}
    if theme is not None:
        if theme not in THEMES:
            raise HTTPException(status_code=422, detail="unknown theme")
        changes["theme"] = theme
    if text_size is not None:
        if text_size not in TEXT_SIZES:
            raise HTTPException(status_code=422, detail="unknown text size")
        changes["text_size"] = text_size
    if changes:
        client = deps.supabase_admin()
        await asyncio.to_thread(
            lambda: (
                client.table("profiles")
                .update(changes)
                .eq("user_id", user.id)
                .execute()
            )
        )
    return Response(status_code=204, headers={"HX-Refresh": "true"})


async def _profile_body(request: Request, user: CurrentUser, profile):
    """The part of the profile page the interest and suggestion buttons refresh."""
    return deps.render(
        request,
        "_profile_body.html",
        lang=profile.edition_lang,
        profile=profile,
        interests=await learning.list_interests(user.id),
        suggestions=await learning.pending_suggestions(user.id),
        notes=await learning.recent_notes(user.id),
    )


@router.get("/profile")
async def profile_page(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """What Subah knows about the reader: interests as bars, their history, suggestions, notes (F-10, F-11)."""
    profile, _ = await edition.profile_today(user.id)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    return deps.render(
        request,
        "profile.html",
        lang=profile.edition_lang,
        profile=profile,
        reader_name=profile.display_name,
        interests=await learning.list_interests(user.id),
        suggestions=await learning.pending_suggestions(user.id),
        notes=await learning.recent_notes(user.id),
        nav_active="profile",
    )


@router.post("/interests", dependencies=[Depends(deps.verify_csrf)])
async def change_interests(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    action: Annotated[str, Form()],
    interest_id: Annotated[str, Form()] = "",
    weight: Annotated[float | None, Form()] = None,
    label: Annotated[str, Form()] = "",
):
    """The reader edits their own interests: `update` the weight, `delete`, or `add` one."""
    profile, _ = await edition.profile_today(user.id)
    if profile is None:
        raise HTTPException(status_code=404)
    if action == "update" and weight is not None:
        ok = await learning.set_weight(user.id, interest_id, weight)
    elif action == "delete":
        ok = await learning.remove_interest(user.id, interest_id)
    elif action == "add":
        ok = await learning.add_interest(user.id, label)
    else:
        raise HTTPException(status_code=422, detail="unknown action")
    if not ok:
        raise HTTPException(status_code=404)
    return await _profile_body(request, user, profile)


@router.post("/suggestions/{suggestion_id}", dependencies=[Depends(deps.verify_csrf)])
async def decide_suggestion(
    request: Request,
    suggestion_id: str,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    decision: Annotated[str, Form()],
    ctx: Annotated[str, Form()] = "",
):
    """Yes adds the suggested interest, No remembers the refusal; the card then disappears."""
    if decision not in ("accept", "reject"):
        raise HTTPException(status_code=422, detail="unknown decision")
    if not await learning.decide_suggestion(
        user.id, suggestion_id, decision == "accept"
    ):
        raise HTTPException(status_code=404)
    if ctx == "profile":
        profile, _ = await edition.profile_today(user.id)
        if profile is None:
            raise HTTPException(status_code=404)
        return await _profile_body(request, user, profile)
    return Response(status_code=200)


async def _settings_page(request: Request, user: CurrentUser, profile, **extra):
    import zoneinfo

    s = await prefs.get_settings(user.id)
    return deps.render(
        request,
        "settings.html",
        lang=s.get("edition_lang", profile.edition_lang),
        profile=profile,
        s=s,
        zones=sorted(zoneinfo.available_timezones()),
        mutes=await prefs.list_mutes(user.id),
        favorites=await prefs.list_favorites(user.id),
        catalog=await _catalog_options(user.id, s.get("edition_lang", "en")),
        nav_active="profile",
        **extra,
    )


async def _catalog_options(user_id: str, lang: str) -> list[dict]:
    from app.services import sources

    taken = {f["catalog_key"] for f in await prefs.list_favorites(user_id)}
    return [o for o in sources.catalog_for(lang) if o["key"] not in taken]


@router.get("/settings")
async def settings_page(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    saved: int = 0,
):
    """Edition, reading comfort, never-show-me words and favorite sources in one place (docs/05_ROUTES.md)."""
    profile, _ = await edition.profile_today(user.id)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    return await _settings_page(request, user, profile, saved=bool(saved))


@router.post("/settings", dependencies=[Depends(deps.verify_csrf)])
async def save_settings(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    profile, _ = await edition.profile_today(user.id)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    form = dict((await request.form()).items())
    try:
        await prefs.save_settings(user.id, form)
    except prefs.PrefsError as exc:
        page = await _settings_page(request, user, profile, error=exc.key)
        page.status_code = 400
        return page
    return RedirectResponse("/settings?saved=1", status_code=303)
