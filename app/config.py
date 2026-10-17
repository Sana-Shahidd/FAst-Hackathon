"""Settings (env vars, docs/03_TECH.md §6) and constants (§5)."""

from __future__ import annotations

import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PAPER_NAME = "Subah"
MAX_MUTES = 30
MAX_CUSTOM_FEEDS = 5
FAVORITE_BOOST = 1.25
PUZZLE_SIZE = 5
WEIGHT_SAVE = 0.10
WEIGHT_PUZZLE = 0.03
SUPPORTED_LANGS = ["en", "ur", "ar", "hi", "bn", "es", "fr", "zh"]
RTL_LANGS = {"ur", "ar"}
READING_TIME_ARTICLES = {5: 8, 10: 14, 20: 22}
MAX_FEED_URLS = 25
FEED_TIMEOUT_S = 6
MAX_CANDIDATES = 120
FRESH_HOURS = 36
FRESH_HOURS_FALLBACK = 72
DEDUPE_THRESHOLD = 85
RECENT_EDITIONS_EXCLUDE = 3
WEIGHT_CLICK = 0.08
WEIGHT_MORE = 0.15
WEIGHT_LESS = -0.15
WEIGHT_DWELL = 0.04
WEIGHT_IGNORED = -0.02
WEIGHT_MIN, WEIGHT_MAX = 0.05, 1.0
LEARNER_MIN_SIGNALS = 5
AGENT_TIMEOUT_S = 25
DEFAULT_DELIVERY_TIME = "06:00"


class Settings(BaseSettings):
    """Environment variables; real values come from `.env` or the host."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "dev"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    SESSION_COOKIE_SECURE: bool = False
    SECRET_KEY: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    PROFILER_MODEL: str = ""
    CURATOR_MODEL: str = ""
    EDITOR_MODEL: str = ""
    LEARNER_MODEL: str = ""
    FALLBACK_MODEL: str = ""
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:you@example.com"
    GIT_SHA: str = "dev"
    TEST_SUPABASE_URL: str = ""
    TEST_SUPABASE_ANON_KEY: str = ""
    TEST_SUPABASE_SERVICE_ROLE_KEY: str = ""

    @model_validator(mode="after")
    def _public_url_from_space(self) -> Settings:
        """On a Hugging Face Space the public address is `https://$SPACE_HOST` unless set explicitly."""
        host = os.getenv("SPACE_HOST")
        if host and self.PUBLIC_BASE_URL.startswith("http://localhost"):
            self.PUBLIC_BASE_URL = f"https://{host}"
        return self

    def production_problems(self) -> tuple[list[str], list[str]]:
        """(errors, warnings) for `APP_ENV=production`: errors stop the app from starting."""
        errors = [
            f"{name} is not set"
            for name in (
                "SECRET_KEY",
                "SUPABASE_URL",
                "SUPABASE_ANON_KEY",
                "SUPABASE_SERVICE_ROLE_KEY",
            )
            if not getattr(self, name)
        ]
        warnings = []
        if not self.SESSION_COOKIE_SECURE:
            warnings.append(
                "SESSION_COOKIE_SECURE is false: session cookies are not marked Secure"
            )
        if self.PUBLIC_BASE_URL.startswith("http://localhost"):
            warnings.append(
                "PUBLIC_BASE_URL still points at localhost: PDF links will be wrong"
            )
        if not (self.GEMINI_API_KEY or self.GROQ_API_KEY):
            warnings.append(
                "no LLM key is set: every edition will use the code fallbacks"
            )
        return errors, warnings

    def model_for(self, key: str) -> str:
        """Primary `provider:model_id` spec for agent `key` (profiler, curator, ...)."""
        specs = {
            "profiler": self.PROFILER_MODEL,
            "curator": self.CURATOR_MODEL,
            "editor": self.EDITOR_MODEL,
            "learner": self.LEARNER_MODEL,
            "answerer": self.EDITOR_MODEL,  # Ask Subah reuses the Editor's model
        }
        if key not in specs:
            raise KeyError(f"unknown agent key: {key}")
        return specs[key]


settings = Settings()
