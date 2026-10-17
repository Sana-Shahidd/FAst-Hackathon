"""Paper routes (docs/05_ROUTES.md). `/paper/today` is a placeholder until T-06/T-07."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app import deps
from app.deps import CurrentUser

router = APIRouter()


@router.get("/paper/today")
async def paper_today(user: Annotated[CurrentUser, Depends(deps.require_user)]):
    raise NotImplementedError("F-07: today's edition page arrives with T-06/T-07")
