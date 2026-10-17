"""Reader preferences (docs/05_ROUTES.md): reading comfort now; settings and profile pages come later."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Response

from app import deps
from app.deps import CurrentUser

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
