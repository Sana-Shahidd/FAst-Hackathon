"""`APP_ENV=production` refuses to start without its secrets and warns about weak settings."""

from __future__ import annotations

import pytest

from app import main
from app.config import Settings

pytestmark = pytest.mark.unit

GOOD = {
    "APP_ENV": "production",
    "SECRET_KEY": "s3cret",
    "SUPABASE_URL": "https://x.supabase.co",
    "SUPABASE_ANON_KEY": "anon",
    "SUPABASE_SERVICE_ROLE_KEY": "service",
    "SESSION_COOKIE_SECURE": True,
    "PUBLIC_BASE_URL": "https://subah.up.railway.app",
    "GEMINI_API_KEY": "g",
}


def make(**overrides) -> Settings:
    return Settings(_env_file=None, **{**GOOD, **overrides})


def test_a_complete_production_setup_has_no_problems() -> None:
    assert make().production_problems() == ([], [])


@pytest.mark.parametrize(
    "name",
    ["SECRET_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"],
)
def test_a_missing_secret_is_an_error(name: str) -> None:
    errors, _ = make(**{name: ""}).production_problems()
    assert errors == [f"{name} is not set"]


def test_weak_but_workable_settings_only_warn() -> None:
    errors, warnings = make(
        SESSION_COOKIE_SECURE=False,
        PUBLIC_BASE_URL="http://localhost:8000",
        GEMINI_API_KEY="",
    ).production_problems()
    assert errors == [] and len(warnings) == 3


def test_the_app_refuses_to_start_in_production_without_a_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "settings", make(SECRET_KEY=""))
    with pytest.raises(RuntimeError, match="SECRET_KEY is not set"):
        main.create_app()


def test_a_complete_production_app_builds_and_hides_the_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "settings", make())
    assert main.create_app().docs_url is None


def test_development_never_runs_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", make(APP_ENV="dev", SECRET_KEY=""))
    assert main.create_app().docs_url == "/docs"
