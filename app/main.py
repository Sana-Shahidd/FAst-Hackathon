"""Subah — FastAPI application (frontend pages + backend API in one service).

Routers, static files, the rate limiter and `GET /health` (docs/05_ROUTES.md,
docs/03_TECH.md §9). The shared Playwright browser and the scheduler join the lifespan in
later tasks.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import deps, jobs
from app.config import settings
from app.routers import (
    archive,
    auth,
    onboarding,
    paper,
    profile,
    puzzle,
    reader,
    signals,
)
from app.services import i18n, pdf

logger = logging.getLogger(__name__)

health_router = APIRouter()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """One shared Chromium for the PDF renderer lives as long as the app (docs/03_TECH.md §9)."""
    await pdf.start_on_startup(application)
    scheduler = jobs.start_scheduler()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    await pdf.stop_browser()


def create_app() -> FastAPI:
    """Build the application; a factory so tests can build a production-mode instance."""
    production = settings.APP_ENV == "production"
    if production:
        errors, warnings = settings.production_problems()
        for warning in warnings:
            logger.warning("production check: %s", warning)
        if errors:
            raise RuntimeError("production check failed: " + "; ".join(errors))
    application = FastAPI(
        title="Subah",
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    application.state.limiter = deps.limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_exception_handler(deps.LoginRequired, login_required)
    application.add_exception_handler(Exception, unexpected_error)
    application.middleware("http")(renew_session_cookies)
    application.mount(
        "/static", StaticFiles(directory=i18n.APP_DIR / "static"), name="static"
    )
    application.include_router(health_router)
    application.include_router(auth.router)
    application.include_router(onboarding.router)
    application.include_router(paper.router)
    application.include_router(archive.router)
    application.include_router(profile.router)
    application.include_router(puzzle.router)
    application.include_router(reader.router)
    application.include_router(signals.router)
    return application


async def login_required(request: Request, exc: deps.LoginRequired) -> Response:
    """Pages go to /login; HTMX fragments and JSON callers get a 401."""
    if request.headers.get("HX-Request") or "application/json" in request.headers.get(
        "accept", ""
    ):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


async def unexpected_error(request: Request, exc: Exception) -> Response:
    """Never show a stack trace (docs/03_TECH.md §7)."""
    logger.exception("unhandled error on %s", request.url.path)
    try:
        return deps.render(request, "error.html", 500)
    except Exception:  # noqa: BLE001 - last resort when templating itself is broken
        return PlainTextResponse("Something went wrong.", status_code=500)


async def renew_session_cookies(request: Request, call_next) -> Response:
    """Store tokens that `deps.optional_user` refreshed during the request."""
    response = await call_next(request)
    renewed = getattr(request.state, "new_session", None)
    if renewed:
        deps.set_session_cookies(response, *renewed)
    return response


VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def version() -> str:
    """Commit sha of this build: `GIT_SHA`, else Railway's, else the `app/VERSION` file, else `"dev"`.

    `scripts/deploy.sh` writes `app/VERSION` before `railway up`, which uploads files without git metadata.
    """
    sha = os.getenv("GIT_SHA", "dev")
    if sha != "dev":
        return sha
    if railway_sha := os.getenv("RAILWAY_GIT_COMMIT_SHA"):
        return railway_sha
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


async def db_ok() -> bool:
    """True when a trivial query against Supabase succeeds."""
    try:
        client = deps.supabase_admin()
        await asyncio.to_thread(
            lambda: client.table("profiles").select("user_id").limit(1).execute()
        )
    except Exception:  # noqa: BLE001 - /health reports the failure instead of raising
        return False
    return True


async def pdf_ok(application: FastAPI) -> bool:
    """True once the shared Playwright browser is alive; started by T-08's lifespan."""
    browser = getattr(application.state, "browser", None)
    return bool(browser is not None and browser.is_connected())


@health_router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Liveness probe: `{"ok": true, "version": …, "db": …, "pdf": …}`."""
    body = {
        "ok": True,
        "version": version(),
        "db": await db_ok(),
        "pdf": await pdf_ok(request.app),
    }
    return JSONResponse(body)


app = create_app()
