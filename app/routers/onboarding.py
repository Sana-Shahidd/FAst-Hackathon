"""Onboarding routes (docs/05_ROUTES.md, F-02): five steps, saved by one POST."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import deps
from app.agents.profiler import parse_interests
from app.config import READING_TIME_ARTICLES, SUPPORTED_LANGS
from app.deps import CurrentUser
from app.services import feeds, i18n, onboarding, sources

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding")
STEPS = 5


def step_context(lang: str) -> dict:
    """What the five step templates need: topics, languages, outlets, reading times."""
    topic_cards = [
        {
            "key": key,
            "icon": info.get("icon", "newspaper"),
            "label": i18n.t(f"topic.{key}", lang),
        }
        for key, info in feeds.topics().items()
    ]
    return {
        "steps": STEPS,
        "topic_cards": topic_cards,
        "catalog": sources.catalog_for(lang),
        "reading_options": sorted(READING_TIME_ARTICLES),
        "edition_lang": lang,
        "language_tiles": [
            {"code": code, "native": info["native"], "name": info["name"]}
            for code, info in i18n.languages().items()
        ],
    }


@router.get("")
async def onboarding_page(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    lang = deps.current_lang(request)
    return deps.render(request, "onboarding.html", **step_context(lang))


@router.get("/step/{n}")
async def onboarding_step(
    n: int, request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """One step as an HTMX fragment; `?lang=` re-renders it in another language."""
    if not 1 <= n <= STEPS:
        raise HTTPException(status_code=404)
    lang = deps.current_lang(request)
    return deps.render(request, f"_ob_step{n}.html", **step_context(lang))


@router.post("/parse", dependencies=[Depends(deps.verify_csrf)])
async def parse(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    text: Annotated[str, Form()] = "",
):
    """Profiler Agent (or the code fallback): free text -> removable interest chips."""
    interests, used_fallback = await parse_interests(text, deps.current_lang(request))
    return deps.render(
        request, "_ob_chips.html", interests=interests, used_fallback=used_fallback
    )


@router.post("/feed", dependencies=[Depends(deps.verify_csrf)])
async def check_feed(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    url: Annotated[str, Form()] = "",
):
    """Validate one pasted RSS/Atom link; returns a chip or an error message."""
    ok, title = await sources.validate_custom_feed(url)
    return deps.render(
        request, "_ob_feed.html", ok=ok, title=title or url.strip(), url=url.strip()
    )


@router.get("/taste")
async def taste(
    request: Request,
    user: Annotated[CurrentUser, Depends(deps.require_user)],
    topics: str = "",
):
    """Eight real headlines for the chosen topics (taste test)."""
    lang = deps.current_lang(request)
    cards = await onboarding.taste_cards(topics.split(","), lang)
    return deps.render(request, "_taste_card.html", cards=cards)


@router.post("", dependencies=[Depends(deps.verify_csrf)])
async def save(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """Validate the whole form, save the reader, then print the first paper."""
    form = await request.form()
    lang = (
        form.get("edition_lang")
        if form.get("edition_lang") in SUPPORTED_LANGS
        else "en"
    )
    try:
        data = onboarding.parse_onboarding(form)
    except onboarding.OnboardingError as exc:
        return deps.render(
            request,
            "onboarding.html",
            400,
            lang=lang,
            error=exc.key,
            **step_context(lang),
        )
    for url in data.custom_feeds:
        ok, title = await sources.validate_custom_feed(url)
        if ok:
            data.custom_feed_names[url] = title or url
    try:
        await onboarding.save_onboarding(user.id, data, user.email)
    except Exception:
        logger.exception("onboarding save failed for %s", user.id)
        return deps.render(
            request,
            "onboarding.html",
            500,
            lang=lang,
            error="auth.error.generic",
            **step_context(lang),
        )
    return RedirectResponse("/paper/generate?first=1", status_code=303)
