"""Pydantic models shared across services (docs/04_DATA.md, docs/06_AGENTS.md §3).

Agent output models (ProfilerOut, CuratorOut, EditorOut, LearnerOut) are added by the
tasks that first use them (T-05, T-06, T-10).
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Profile(BaseModel):
    """Row of `profiles`; only the columns the services read."""

    model_config = ConfigDict(extra="ignore")

    user_id: str = ""
    display_name: str = "Reader"
    edition_lang: str = "en"
    source_langs: list[str] = Field(default_factory=list)
    city: str | None = None
    timezone: str = "UTC"
    reading_minutes: int = 10


class Interest(BaseModel):
    """Row of `interests`."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    label: str
    topic_key: str | None = None
    query: str
    weight: float = 0.5
    source: str = "onboarding"
    active: bool = True


class FavoriteSource(BaseModel):
    """Row of `favorite_sources` (F-23)."""

    model_config = ConfigDict(extra="ignore")

    catalog_key: str | None = None
    name: str
    feed_url: str
    kind: str = "catalog"


class FeedUrl(BaseModel):
    """One feed to fetch: where it came from decides how candidates are tagged."""

    url: str
    lang: str
    kind: str  # topic | interest | city | curated | favorite | custom
    name: str = ""
    topic_key: str | None = None
    interest_id: str | None = None
    favorite: bool = False


class Candidate(BaseModel):
    """A fetched feed item before ranking (`articles` row plus how it was found)."""

    url: str
    title: str
    source_name: str = ""
    summary: str = ""
    image_url: str | None = None
    lang: str = "en"
    published_at: datetime | None = None
    topic_key: str | None = None
    interest_id: str | None = None
    favorite: bool = False

    @property
    def url_hash(self) -> str:
        """sha256 of the normalised URL: the `articles.url_hash` upsert key."""
        return hashlib.sha256(self.url.strip().rstrip("/").lower().encode()).hexdigest()

    @property
    def id(self) -> str:
        """Short id the Curator sees; the code validates every id it returns."""
        return self.url_hash[:12]
