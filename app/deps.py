"""Shared dependencies: Supabase clients, language, templates + t(), CSRF, sessions.

Session = Supabase access + refresh token in HttpOnly cookies (AGENTS.md Rule 3).
The service-role client never leaves the server.
"""

from __future__ import annotations

import asyncio
import hmac
import secrets
from dataclasses import dataclass
from functools import cache, lru_cache
from hashlib import sha256
from urllib.parse import quote

from fastapi import HTTPException, Request, Response
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address
from supabase_auth.errors import AuthError

from app.config import PAPER_NAME, SUPPORTED_LANGS, settings
from app.services import i18n
from supabase import Client, create_client

ACCESS_COOKIE = "sb_access"
REFRESH_COOKIE = "sb_refresh"
CSRF_COOKIE = "sb_csrf"
LANG_COOKIE = "lang"
ACCESS_MAX_AGE = 60 * 60
REFRESH_MAX_AGE = 60 * 60 * 24 * 30

limiter = Limiter(key_func=get_remote_address)
templates = Jinja2Templates(directory=str(i18n.APP_DIR / "templates"))


# ---------------------------------------------------------------- Supabase


@lru_cache(maxsize=1)
def supabase_admin() -> Client:
    """Service-role Supabase client. Server-side only; the key never reaches the browser."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def supabase_anon() -> Client:
    """A fresh anon-key client for one auth call (its auth state is per client, so no sharing)."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY are not set")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


# ---------------------------------------------------------------- language


def current_lang(request: Request) -> str:
    """UI language: `?lang=` (validated), else the remembered cookie, else English."""
    for candidate in (
        request.query_params.get("lang"),
        request.cookies.get(LANG_COOKIE),
    ):
        if candidate in SUPPORTED_LANGS:
            return candidate
    return i18n.DEFAULT_LANG


@cache
def fonts_url(lang: str) -> str:
    """One Google Fonts stylesheet URL for the Latin UI fonts plus this language's fonts."""
    meta = i18n.languages()[lang]
    families = {"DM Serif Display", "Inter", "Source Serif 4"}
    families |= {meta["font_display"], meta["font_body"], meta["font_ui"]}
    parts = "&".join(
        f"family={quote(name).replace('%20', '+')}" for name in sorted(families)
    )
    return f"https://fonts.googleapis.com/css2?{parts}&display=swap"


# -------------------------------------------------------------------- CSRF


@cache
def _ephemeral_key() -> str:
    return secrets.token_urlsafe(32)


def _sign(value: str) -> str:
    key = settings.SECRET_KEY or _ephemeral_key()
    return hmac.new(key.encode(), value.encode(), sha256).hexdigest()


async def verify_csrf(request: Request) -> None:
    """Dependency for POST routes: the form/header token must match the CSRF cookie."""
    cookie = request.cookies.get(CSRF_COOKIE)
    supplied = request.headers.get("X-CSRF-Token")
    if supplied is None:
        supplied = str((await request.form()).get("csrf_token", ""))
    if not cookie or not hmac.compare_digest(supplied, _sign(cookie)):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


# ---------------------------------------------------------------- rendering


def render(
    request: Request,
    name: str,
    status_code: int = 200,
    *,
    lang: str | None = None,
    profile: object | None = None,
    **context: object,
) -> Response:
    """Render a page with the language, direction, theme, fonts, `t()` and a CSRF token."""
    lang = lang or current_lang(request)
    meta = i18n.languages()[lang]
    csrf_id = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24)
    page = {
        "lang": lang,
        "dir": i18n.dir(lang),
        "theme": getattr(profile, "theme", "auto"),
        "text_size": getattr(profile, "text_size", "M"),
        "fonts_url": fonts_url(lang),
        "font_display": meta["font_display"],
        "font_ui": meta["font_ui"],
        "languages": [
            (code, info["native"]) for code, info in i18n.languages().items()
        ],
        "paper_name": PAPER_NAME,
        "csrf_token": _sign(csrf_id),
        "path": request.url.path,
        "t": lambda key, **vars: i18n.t(key, lang, **vars),
        **context,
    }
    response = templates.TemplateResponse(request, name, page, status_code=status_code)
    secure = settings.SESSION_COOKIE_SECURE
    if CSRF_COOKIE not in request.cookies:
        response.set_cookie(
            CSRF_COOKIE, csrf_id, httponly=True, samesite="lax", secure=secure
        )
    if request.query_params.get("lang") == lang:
        response.set_cookie(
            LANG_COOKIE, lang, samesite="lax", secure=secure, max_age=REFRESH_MAX_AGE
        )
    return response


# ---------------------------------------------------------------- sessions


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str


class LoginRequired(Exception):
    """Raised by `require_user`; main.py turns it into a redirect or a 401."""


def set_session_cookies(response: Response, access: str, refresh: str) -> None:
    secure = settings.SESSION_COOKIE_SECURE
    options = {"httponly": True, "samesite": "lax", "secure": secure}
    response.set_cookie(ACCESS_COOKIE, access, max_age=ACCESS_MAX_AGE, **options)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=REFRESH_MAX_AGE, **options)


def clear_session_cookies(response: Response) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name)


def _user_from_token(token: str) -> CurrentUser | None:
    try:
        result = supabase_anon().auth.get_user(token)
    except (AuthError, RuntimeError):
        return None
    user = getattr(result, "user", None)
    return CurrentUser(id=str(user.id), email=user.email or "") if user else None


def _refresh(refresh_token: str) -> tuple[CurrentUser, str, str] | None:
    try:
        session = supabase_anon().auth.refresh_session(refresh_token).session
    except (AuthError, RuntimeError):
        return None
    if session is None or session.user is None:
        return None
    user = CurrentUser(id=str(session.user.id), email=session.user.email or "")
    return user, session.access_token, session.refresh_token


async def optional_user(request: Request) -> CurrentUser | None:
    """The signed-in user, refreshing an expired access token; None when signed out."""
    access = request.cookies.get(ACCESS_COOKIE)
    if access and (user := await asyncio.to_thread(_user_from_token, access)):
        return user
    refresh = request.cookies.get(REFRESH_COOKIE)
    if refresh and (renewed := await asyncio.to_thread(_refresh, refresh)):
        user, new_access, new_refresh = renewed
        request.state.new_session = (
            new_access,
            new_refresh,
        )  # cookies set by middleware
        return user
    return None


async def require_user(request: Request) -> CurrentUser:
    """Dependency for signed-in routes; signed-out visitors go to /login (401 for fragments)."""
    user = await optional_user(request)
    if user is None:
        raise LoginRequired
    return user
