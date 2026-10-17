"""Landing page, signup, login, logout (docs/05_ROUTES.md, F-01)."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from supabase_auth.errors import AuthApiError, AuthError

from app import deps
from app.deps import CurrentUser

logger = logging.getLogger(__name__)
router = APIRouter()

EXISTS_CODES = {"user_already_exists", "email_exists"}
WEAK_CODES = {"weak_password", "email_address_invalid", "validation_failed"}


async def home_path(user_id: str) -> str:
    """Where a signed-in user lands: today's paper, or onboarding until it is finished."""
    try:
        client = deps.supabase_admin()
        rows = await asyncio.to_thread(
            lambda: (
                client.table("profiles")
                .select("onboarded_at")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
                .data
            )
        )
    except Exception:
        logger.exception("profile lookup failed")
        return "/onboarding"
    return "/paper/today" if rows and rows[0].get("onboarded_at") else "/onboarding"


async def ensure_profile(user_id: str, email: str) -> None:
    """Create the `profiles` row for a new user (display name = email local part)."""
    client = deps.supabase_admin()
    row = {"user_id": user_id, "display_name": (email.split("@")[0] or "Reader")[:40]}
    await asyncio.to_thread(
        lambda: (
            client.table("profiles")
            .upsert(row, on_conflict="user_id", ignore_duplicates=True)
            .execute()
        )
    )


def signed_in(response: Response, session) -> None:
    deps.set_session_cookies(response, session.access_token, session.refresh_token)


@router.get("/")
async def landing(request: Request):
    user = await deps.optional_user(request)
    if user:
        return RedirectResponse(await home_path(user.id), status_code=303)
    return deps.render(request, "landing.html")


@router.get("/signup")
async def signup_page(request: Request):
    return deps.render(request, "signup.html", mode="signup")


@router.get("/login")
async def login_page(request: Request):
    return deps.render(request, "login.html", mode="login")


@router.post("/signup", dependencies=[Depends(deps.verify_csrf)])
@deps.limiter.limit("5/minute")
async def signup(
    request: Request,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
):
    email = email.strip().lower()
    if "@" not in email or len(email) > 254 or len(password) < 6:
        return deps.render(
            request,
            "signup.html",
            400,
            mode="signup",
            error="auth.error.weak",
            email=email,
        )
    try:
        result = await asyncio.to_thread(
            lambda: deps.supabase_anon().auth.sign_up(
                {"email": email, "password": password}
            )
        )
        if result.user is None or result.session is None:
            raise AuthError("sign-up returned no session", "no_session")
        await ensure_profile(str(result.user.id), email)
    except AuthApiError as exc:
        key = (
            "auth.error.exists"
            if exc.code in EXISTS_CODES or "already" in exc.message.lower()
            else "auth.error.weak"
            if exc.code in WEAK_CODES
            else "auth.error.generic"
        )
        return deps.render(
            request, "signup.html", 400, mode="signup", error=key, email=email
        )
    except Exception:
        logger.exception("signup failed")
        return deps.render(
            request,
            "signup.html",
            500,
            mode="signup",
            error="auth.error.generic",
            email=email,
        )
    response = RedirectResponse("/onboarding", status_code=303)
    signed_in(response, result.session)
    return response


@router.post("/login", dependencies=[Depends(deps.verify_csrf)])
@deps.limiter.limit("10/minute")
async def login(
    request: Request,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
):
    email = email.strip().lower()
    try:
        result = await asyncio.to_thread(
            lambda: deps.supabase_anon().auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        )
        if result.user is None or result.session is None:
            raise AuthError("login returned no session", "no_session")
    except AuthApiError:
        return deps.render(
            request,
            "login.html",
            400,
            mode="login",
            error="auth.error.credentials",
            email=email,
        )
    except Exception:
        logger.exception("login failed")
        return deps.render(
            request,
            "login.html",
            500,
            mode="login",
            error="auth.error.generic",
            email=email,
        )
    response = RedirectResponse(await home_path(str(result.user.id)), status_code=303)
    signed_in(response, result.session)
    return response


@router.post("/logout", dependencies=[Depends(deps.verify_csrf)])
async def logout(
    request: Request, user: Annotated[CurrentUser, Depends(deps.require_user)]
):
    """Revoke the Supabase session server-side, then clear the cookies."""
    token = request.cookies.get(deps.ACCESS_COOKIE, "")
    try:
        admin = deps.supabase_admin()
        await asyncio.to_thread(lambda: admin.auth.admin.sign_out(token))
    except Exception:  # noqa: BLE001 - cookies are cleared even if revocation fails
        logger.warning("could not revoke session for %s", user.id)
    response = RedirectResponse("/", status_code=303)
    deps.clear_session_cookies(response)
    return response
