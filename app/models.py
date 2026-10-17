"""Pydantic models shared across services (docs/04_DATA.md, docs/06_AGENTS.md §3).

Agent output models (ProfilerOut, CuratorOut, EditorOut, LearnerOut) are added by the
tasks that first use them (T-05, T-06, T-10).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


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
    text_size: str = "M"
    theme: str = "auto"


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

    @property
    def section(self) -> str:
        """Section key: topic key, `i_<interest id>` for custom interests, else `world`."""
        if self.topic_key:
            return self.topic_key
        return f"i_{self.interest_id[:8]}" if self.interest_id else "world"


class ParsedInterest(BaseModel):
    label: str = Field(max_length=60)  # in the user's language
    query: str = Field(max_length=200)  # Google News search query


class ProfilerOut(BaseModel):
    interests: list[ParsedInterest] = Field(max_length=5)


class TopicChoice(BaseModel):
    """A topic picked in onboarding step 2, with its "how much" weight."""

    key: str
    weight: float


class OnboardingData(BaseModel):
    """Validated `POST /onboarding` form (docs/05_ROUTES.md "Onboarding form fields")."""

    edition_lang: str = "en"
    source_langs: list[str] = Field(default_factory=list)
    topics: list[TopicChoice]
    custom_interests: list[ParsedInterest] = Field(default_factory=list)
    taste: dict[str, float] = Field(default_factory=dict)  # topic key -> net vote delta
    display_name: str | None = None
    city: str | None = None
    timezone: str = "UTC"
    reading_minutes: int = 10
    favorite_sources: list[str] = Field(default_factory=list)  # catalog keys
    custom_feeds: list[str] = Field(default_factory=list)  # feed URLs (shape-checked)
    custom_feed_names: dict[str, str] = Field(
        default_factory=dict
    )  # URL -> title, once validated
    muted_keywords: list[str] = Field(default_factory=list)
    notify: bool = False


# ------------------------------------------------------------ edition models
# Docs 06_AGENTS.md §3. Over-long text from an LLM is trimmed instead of rejected, so one
# long headline cannot throw away a whole edition; the schema the model sees still states
# the limits.


def _trim(limit: int) -> BeforeValidator:
    return BeforeValidator(lambda v: v[:limit] if isinstance(v, str) else v)


def _cap(limit: int) -> BeforeValidator:
    return BeforeValidator(lambda v: v[:limit] if isinstance(v, list) else v)


def _clamp_importance(value: object) -> object:
    return min(10, max(1, value)) if isinstance(value, int) else value


class Pick(BaseModel):
    candidate_id: str  # must be one of the given ids
    section: Annotated[
        str, _trim(40), Field(max_length=40)
    ]  # topic key, 'your_city' or 'world'
    importance: Annotated[int, BeforeValidator(_clamp_importance), Field(ge=1, le=10)]
    reason: Annotated[
        str, _trim(120), Field(max_length=120)
    ]  # English, for making-of + 'why'


class CuratorOut(BaseModel):
    picks: Annotated[list[Pick], _cap(30), Field(max_length=30)]
    notes: Annotated[str, _trim(200), Field(max_length=200)] = ""


class WrittenArticle(BaseModel):
    candidate_id: str
    headline: Annotated[str, _trim(110), Field(max_length=110)]  # edition language
    summary: Annotated[str, _trim(420), Field(max_length=420)]  # 1-3 sentences
    why: Annotated[str, _trim(100), Field(max_length=100)] = (
        ""  # "Because you follow ..."
    )


class PuzzleItem(BaseModel):
    candidate_id: str
    masked_headline: Annotated[
        str, _trim(120), Field(max_length=120)
    ]  # answer replaced by "___"
    answer: Annotated[
        str, _trim(30), Field(max_length=30)
    ]  # exactly as in the headline
    decoys: Annotated[list[str], _cap(3), Field(min_length=3, max_length=3)]


class EditorOut(BaseModel):
    lead_headline: Annotated[str, _trim(110), Field(max_length=110)]
    lead_dek: Annotated[str, _trim(240), Field(max_length=240)]
    articles: Annotated[list[WrittenArticle], _cap(30), Field(max_length=30)]
    section_titles: dict[str, str] = Field(default_factory=dict)  # section key -> title
    three_things: Annotated[
        list[Annotated[str, _trim(120)]], _cap(3), Field(min_length=3, max_length=3)
    ]
    editor_note: Annotated[str, _trim(240), Field(max_length=240)] = ""
    puzzle: Annotated[list[PuzzleItem], _cap(5), Field(max_length=5)] = Field(
        default_factory=list
    )


class PlacedArticle(BaseModel):
    """A pick with its slot (lead / secondary / brief) and reading position."""

    candidate_id: str
    section: str
    slot: str
    position: int
    importance: int
    reason: str = ""


class Reader(BaseModel):
    """Everything the Curator and Editor are told about one reader (never emails or ids)."""

    lang: str = "en"
    name: str = "Reader"
    n: int = 14  # articles in the paper
    city: str | None = None
    weights: dict[str, float] = Field(
        default_factory=dict
    )  # section key -> interest weight
    labels: dict[str, str] = Field(
        default_factory=dict
    )  # section key -> interest label
    favorite_sources: list[str] = Field(default_factory=list)
    blocked_sources: list[str] = Field(default_factory=list)
    liked: list[str] = Field(default_factory=list)  # recent headlines liked
    disliked: list[str] = Field(default_factory=list)
