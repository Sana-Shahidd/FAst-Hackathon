"""Ask Subah (docs/02_PRD.md F-24): find the stories that match a question, then let the Answerer write.

Today's paper is searched first, then a live Google News search for the question; ranking is plain
keyword overlap in code, so the model only ever sees a handful of relevant stories.
"""

from __future__ import annotations

import asyncio
import logging
import re

from app.agents import answerer
from app.models import FeedUrl
from app.services import edition, feeds, puzzle, reading

logger = logging.getLogger(__name__)

MAX_QUESTION = 200
MAX_DOCS = 8
FALLBACK_SOURCES = 3
PAPER_BONUS = (
    1.5  # a story from the reader's own paper beats an equally good live result
)
LIVE_TIMEOUT_S = 8
LIVE_FRESH_HOURS = 72
_WORD = re.compile(r"[^\W_]+")
_HAN = re.compile(r"[一-鿿]")
# question filler the stopword lists do not cover (they never help to find a story)
_QUESTION_WORDS = {
    "what",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "why",
    "how",
    "about",
    "tell",
    "give",
    "any",
    "there",
    "latest",
    "news",
}


def tokens(text: str, lang: str) -> set[str]:
    """Lower-cased content words (stopwords and 1-2 letter words dropped); Chinese uses character pairs."""
    text = text.lower()
    found: set[str] = set()
    for word in _WORD.findall(text):
        if _HAN.search(word):
            found |= {word[i : i + 2] for i in range(max(1, len(word) - 1))}
        elif (
            len(word) >= 3
            and word not in puzzle.stopwords(lang)
            and word not in _QUESTION_WORDS
        ):
            found.add(word)
    return found


def score(question_tokens: set[str], doc: dict, lang: str) -> float:
    """Keyword overlap: a word in the title counts double, a word in the summary once."""
    if not question_tokens:
        return 0.0
    title = tokens(doc["title"], lang)
    body = tokens(doc["summary"], lang)
    value = 2.0 * len(question_tokens & title) + 1.0 * len(
        question_tokens & (body - title)
    )
    return value + (PAPER_BONUS if value and doc["internal_id"] else 0.0)


def rank(
    question: str, docs: list[dict], lang: str, limit: int = MAX_DOCS
) -> list[dict]:
    """The best-matching distinct stories (no zero-overlap stories), best first."""
    wanted = tokens(question, lang)
    seen: set[str] = set()
    scored = []
    for doc in docs:
        key = doc["title"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        points = score(wanted, doc, lang)
        if points > 0:
            scored.append((points, doc))
    scored.sort(key=lambda item: -item[0])
    return [doc for _, doc in scored[:limit]]


def safe_url(url: str) -> str | None:
    """Only http(s) links from a feed are ever shown."""
    return url if url.lower().startswith(("http://", "https://")) else None


async def paper_docs(user_id: str, edition_id: str | None) -> list[dict]:
    if not edition_id:
        return []
    return [
        {
            "title": row["headline"],
            "source": (row.get("articles") or {}).get("source_name") or "",
            "summary": row["summary"],
            "url": f"/r/{row['id']}",
            "internal_id": row["id"],
        }
        for row in await reading.edition_articles(edition_id)
    ]


async def live_docs(question: str, lang: str) -> list[dict]:
    """Fresh Google News results for the question; a slow or failing search just yields nothing."""
    feed = FeedUrl(
        url=feeds.google_news_url(question, lang), lang=lang, kind="interest"
    )
    try:
        found = await asyncio.wait_for(feeds.fetch_all([feed]), LIVE_TIMEOUT_S)
    except Exception:
        logger.warning("live news search failed", exc_info=True)
        return []
    found = feeds.filter_fresh(found, LIVE_FRESH_HOURS) or found
    return [
        {
            "title": c.title,
            "source": c.source_name,
            "summary": c.summary,
            "url": safe_url(c.url),
            "internal_id": None,
        }
        for c in found
        if safe_url(c.url)
    ]


async def ask(user_id: str, question: str, lang: str, edition_id: str | None) -> dict:
    """`{answer, sources, used_ai}`: the Answerer's text plus the stories it used (or the closest ones)."""
    question = " ".join(question.split())[:MAX_QUESTION]
    docs = rank(
        question,
        [*await paper_docs(user_id, edition_id), *await live_docs(question, lang)],
        lang,
    )
    if not docs:
        return {"answer": "", "sources": [], "used_ai": False}
    result = await answerer.answer(question, lang, docs)
    if result is None:
        return {"answer": "", "sources": docs[:FALLBACK_SOURCES], "used_ai": False}
    cited = [docs[n - 1] for n in result.used] or docs[:FALLBACK_SOURCES]
    return {"answer": result.answer, "sources": cited, "used_ai": True}


async def todays_edition_id(user_id: str) -> tuple[object | None, str | None]:
    """(profile, id of the reader's newest ready paper for their local date)."""
    profile, today = await edition.profile_today(user_id)
    if profile is None:
        return None, None
    ready = await edition.ready_edition(user_id, today)
    return profile, ready["id"] if ready else None
