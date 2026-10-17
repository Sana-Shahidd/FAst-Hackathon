"""Reading routes (docs/05_ROUTES.md): the article sheet and the save toggle (F-07, F-19, F-22)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import deps
from app.deps import CurrentUser
from app.services import edition, i18n, prefs, reading, sources

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


async def _saved_context(user: CurrentUser, lang: str) -> dict:
    groups = reading.group_saved(await reading.saved_stories(user.id))
    return {
        "groups": groups,
        "day_labels": {
            day: i18n.full_date(date.fromisoformat(day), lang) for day, _ in groups
        },
    }


async def _saved_list(request: Request, user: CurrentUser, lang: str):
    return deps.render(
        request, "_saved_list.html", lang=lang, **await _saved_context(user, lang)
    )


@router.get("/saved")
async def saved_page(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """Saved for later (F-19), grouped by edition date, newest first."""
    profile, _ = await edition.profile_today(user.id)
    if profile is None:
        return RedirectResponse("/onboarding", status_code=303)
    lang = profile.edition_lang
    return deps.render(
        request,
        "saved.html",
        lang=lang,
        profile=profile,
        nav_active="saved",
        **await _saved_context(user, lang),
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
    if ctx == "saved":
        profile, _ = await edition.profile_today(user.id)
        return await _saved_list(
            request, user, profile.edition_lang if profile else "en"
        )
    art = await reading.card_state(user.id, art)
    return deps.render(
        request, "_article.html", lang=art["editions"]["lang"], art=art, oob=False
    )


@router.post("/mutes", dependencies=[Depends(deps.verify_csrf)])
async def change_mutes(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    action: Annotated[str, Form()],
    keyword: Annotated[str, Form()] = "",
):
    """Add or remove one "never show me" word; returns the refreshed chips (F-18)."""
    error = None
    if action == "add":
        try:
            await prefs.add_mute(user.id, keyword)
        except prefs.PrefsError as exc:
            error = exc.key
    elif action == "remove":
        await prefs.remove_mute(user.id, keyword)
    else:
        raise HTTPException(status_code=422, detail="unknown action")
    profile, _ = await edition.profile_today(user.id)
    return deps.render(
        request,
        "_mutes.html",
        lang=profile.edition_lang if profile else "en",
        mutes=await prefs.list_mutes(user.id),
        mute_error=error,
    )


@router.get("/sources")
async def sources_page(user: Annotated[CurrentUser, Depends(deps.require_user)]):
    return RedirectResponse("/settings#sources-card", status_code=303)


@router.post("/sources", dependencies=[Depends(deps.verify_csrf)])
async def change_sources(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    action: Annotated[str, Form()],
    catalog_key: Annotated[str, Form()] = "",
    feed_url: Annotated[str, Form()] = "",
    id: Annotated[str, Form()] = "",
):
    """Favorite sources: add from the catalog, add a pasted feed (validated), or remove (F-23)."""
    profile, _ = await edition.profile_today(user.id)
    lang = profile.edition_lang if profile else "en"
    error = None
    try:
        if action == "add_catalog":
            await prefs.add_catalog_source(user.id, catalog_key, lang)
        elif action == "add_custom":
            await prefs.add_custom_source(user.id, feed_url)
        elif action == "remove":
            await prefs.remove_source(user.id, id)
        else:
            raise HTTPException(status_code=422, detail="unknown action")
    except prefs.PrefsError as exc:
        error = exc.key
    taken = {f["catalog_key"] for f in await prefs.list_favorites(user.id)}
    return deps.render(
        request,
        "_sources_list.html",
        lang=lang,
        favorites=await prefs.list_favorites(user.id),
        catalog=[o for o in sources.catalog_for(lang) if o["key"] not in taken],
        source_error=error,
    )
