"""Settings (env vars, docs/03_TECH.md §6) and constants (§5)."""

from __future__ import annotations

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

    def model_for(self, key: str) -> str:
        """Primary `provider:model_id` spec for agent `key` (profiler, curator, ...)."""
        specs = {
            "profiler": self.PROFILER_MODEL,
            "curator": self.CURATOR_MODEL,
            "editor": self.EDITOR_MODEL,
            "learner": self.LEARNER_MODEL,
        }
        if key not in specs:
            raise KeyError(f"unknown agent key: {key}")
        return specs[key]


settings = Settings()
