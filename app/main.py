"""Subah — FastAPI application (frontend pages + backend API in one service).

T-01 ships only `GET /health`, the probe the deploy pipeline waits on
(docs/05_ROUTES.md, docs/03_TECH.md §9). Routers, the Supabase client, the shared
Playwright browser and the scheduler are added by later tasks.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

app = FastAPI(title="Subah")


def version() -> str:
    """Commit sha of this build: `GIT_SHA`, else Render's, else `"dev"`."""
    sha = os.getenv("GIT_SHA", "dev")
    return sha if sha != "dev" else os.getenv("RENDER_GIT_COMMIT", "dev")


async def db_ok() -> bool:
    """True once a Supabase query succeeds; T-02 attaches the client to `app.state`."""
    return getattr(app.state, "supabase", None) is not None


async def pdf_ok() -> bool:
    """True once the shared Playwright browser is alive; started by T-08's lifespan."""
    browser = getattr(app.state, "browser", None)
    return bool(browser is not None and browser.is_connected())


@app.get("/health")
async def health() -> dict[str, str | bool]:
    """Liveness probe: `{"ok": true, "version": …, "db": …, "pdf": …}`."""
    return {
        "ok": True,
        "version": version(),
        "db": await db_ok(),
        "pdf": await pdf_ok(),
    }
