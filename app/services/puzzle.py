"""Headline puzzle ("Fill the headline", F-17): build, validate and pad items.

Stored items look like `{"candidate_id", "masked_headline", "answer", "choices": [4]}`; the
pipeline swaps `candidate_id` for `edition_article_id` when it saves them. Grading and
streaks arrive with the puzzle page (T-11).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from datetime import UTC, date, datetime, timedelta
from functools import cache

from app import deps
from app.config import PUZZLE_SIZE
from app.models import EditorOut, PlacedArticle
from app.services import i18n

BLANK = "___"
MIN_WORD = 4
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")
_HAN = re.compile(r"[一-鿿]+")


@cache
def stopwords(lang: str) -> frozenset[str]:
    data = json.loads((i18n.DATA_DIR / "stopwords.json").read_text(encoding="utf-8"))
    return frozenset(w.lower() for w in data.get(lang, []))


def _candidates(headline: str, lang: str) -> list[str]:
    """Words (or, for Chinese, 2-character spans) that could be hidden or used as decoys."""
    stop = stopwords(lang)
    if lang == "zh":
        return [
            run[:2]
            for run in _HAN.findall(headline)
            if len(run) >= 2 and run[:2] not in stop
        ]
    return [
        w
        for w in _WORD.findall(headline)
        if len(w) >= MIN_WORD and w.lower() not in stop
    ]


def mask(headline: str, answer: str, lang: str) -> str | None:
    """`headline` with the first whole-word `answer` replaced by `___`, else None."""
    if lang == "zh":
        return headline.replace(answer, BLANK, 1) if answer in headline else None
    masked, hits = re.subn(
        rf"(?<!\w){re.escape(answer)}(?!\w)", BLANK, headline, count=1
    )
    return masked if hits else None


def _shuffled(answer: str, decoys: list[str], seed: str) -> list[str]:
    choices = [answer, *decoys]
    digest = hashlib.sha256(f"{seed}|{answer}".encode()).digest()
    random.Random(int.from_bytes(digest[:8], "big")).shuffle(choices)
    return choices


def _item(cid: str, headline: str, others: list[str], lang: str) -> dict | None:
    """Fallback item for one headline: longest non-stopword, decoys of similar length."""
    options = _candidates(headline, lang)
    if not options:
        return None
    answer = max(options, key=len)  # max keeps the first of equal lengths
    masked = mask(headline, answer, lang)
    pool: dict[str, str] = {}
    for other in others:
        for word in _candidates(other, lang):
            if word.lower() != answer.lower() and word.lower() not in headline.lower():
                pool.setdefault(word.lower(), word)
    decoys = sorted(
        pool.values(), key=lambda w: (abs(len(w) - len(answer)), w.lower())
    )[:3]
    if masked is None or len(decoys) < 3:
        return None
    return {
        "candidate_id": cid,
        "masked_headline": masked,
        "answer": answer,
        "choices": _shuffled(answer, decoys, cid),
        "source": "code",
    }


def fallback_items(
    placed: list[PlacedArticle],
    headlines: dict[str, str],
    lang: str,
    n: int = PUZZLE_SIZE,
    skip: frozenset[str] = frozenset(),
) -> list[dict]:
    """Code-built items (no AI), in reading order, skipping ids in `skip`."""
    ordered = [p.candidate_id for p in sorted(placed, key=lambda p: p.position)]
    items: list[dict] = []
    for cid in ordered:
        if len(items) >= n:
            break
        if cid in skip or cid not in headlines:
            continue
        others = [headlines[o] for o in ordered if o != cid and o in headlines]
        item = _item(cid, headlines[cid], others, lang)
        if item:
            items.append(item)
    return items


def _valid_editor_item(item, headlines: dict[str, str]) -> dict | None:
    """Keep an Editor item only if hiding the answer really reproduces the written headline."""
    headline = headlines.get(item.candidate_id)
    answer = item.answer.strip()
    decoys = [d.strip() for d in item.decoys]
    if headline is None or not answer or item.masked_headline.count(BLANK) != 1:
        return None
    if item.masked_headline.replace(BLANK, answer, 1) != headline:
        return None
    lowered = [d.lower() for d in decoys]
    if "" in lowered or len(set(lowered)) != 3 or answer.lower() in lowered:
        return None
    return {
        "candidate_id": item.candidate_id,
        "masked_headline": item.masked_headline,
        "answer": answer,
        "choices": _shuffled(answer, decoys, item.candidate_id),
        "source": "editor",
    }


def items_from_editor(
    out: EditorOut | None,
    placed: list[PlacedArticle],
    headlines: dict[str, str],
    lang: str,
    n: int = PUZZLE_SIZE,
) -> list[dict]:
    """Validated Editor items first (one per article), then code fallbacks up to `n`."""
    items: list[dict] = []
    used: set[str] = set()
    for raw in out.puzzle if out else []:
        valid = _valid_editor_item(raw, headlines)
        if valid and valid["candidate_id"] not in used and len(items) < n:
            items.append(valid)
            used.add(valid["candidate_id"])
    if len(items) < n:
        items += fallback_items(
            placed, headlines, lang, n - len(items), frozenset(used)
        )
    return items


# ------------------------------------------------------------ playing (F-17)


def restore(item: dict) -> str:
    """The full headline: the hidden word put back."""
    return item["masked_headline"].replace(BLANK, item["answer"], 1)


def split_blank(item: dict) -> tuple[str, str]:
    """The masked headline around its blank, so the page can underline the gap."""
    before, _, after = item["masked_headline"].partition(BLANK)
    return before, after


def check(
    items: list[dict], answers: list[dict], q: int, choice: str
) -> tuple[dict, bool]:
    """Pure grading: (the record for question `q`, whether it is new).

    Idempotent: a question answered before returns its first answer. Raises ValueError for a
    question out of range or a choice that is not one of that question's four.
    """
    if not 0 <= q < len(items):
        raise ValueError("question out of range")
    earlier = next((a for a in answers if a["q"] == q), None)
    if earlier is not None:
        return earlier, False
    item = items[q]
    if choice not in item["choices"]:
        raise ValueError("not one of the choices")
    return {"q": q, "choice": choice, "correct": choice == item["answer"]}, True


def summarize(answers: list[dict], total: int) -> dict:
    """`{answered, score, done, next_q}` for a set of answers."""
    answered = {a["q"] for a in answers}
    return {
        "answered": len(answered),
        "score": sum(1 for a in answers if a["correct"]),
        "done": len(answered) >= total > 0,
        "next_q": next((q for q in range(total) if q not in answered), None),
    }


def streak_from_dates(days: list[date], today: date) -> int:
    """Consecutive days with a finished puzzle, ending today (or yesterday: today is still playable)."""
    finished = set(days)
    cursor = today if today in finished else today - timedelta(days=1)
    count = 0
    while cursor in finished:
        count += 1
        cursor -= timedelta(days=1)
    return count


async def _db(fn):
    return await asyncio.to_thread(fn)


async def get_items(edition_id: str) -> list[dict] | None:
    """The edition's questions, or None when it has no puzzle."""
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("puzzles")
            .select("items")
            .eq("edition_id", edition_id)
            .limit(1)
            .execute()
            .data
        )
    )
    return rows[0]["items"] if rows else None


async def get_attempt(user_id: str, edition_id: str) -> list[dict]:
    """The reader's answers so far for this edition's puzzle."""
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("puzzle_attempts")
            .select("answers")
            .eq("user_id", user_id)
            .eq("edition_id", edition_id)
            .limit(1)
            .execute()
            .data
        )
    )
    return rows[0]["answers"] if rows else []


async def grade(user_id: str, edition_id: str, q: int, choice: str) -> dict:
    """Grade one answer and save it: `{correct, answer, score, done}`.

    A correct answer raises the story's interest a little (`puzzle_correct` signal). Raises
    `LookupError` when the edition has no puzzle and `ValueError` for a bad question or choice.
    """
    from app.services import reading

    items = await get_items(edition_id)
    if items is None:
        raise LookupError(edition_id)
    answers = await get_attempt(user_id, edition_id)
    record, is_new = check(items, answers, q, choice)
    if is_new:
        answers = [*answers, record]
        summary = summarize(answers, len(items))
        row = {
            "user_id": user_id,
            "edition_id": edition_id,
            "answers": answers,
            "score": summary["score"],
            "completed_at": datetime.now(UTC).isoformat() if summary["done"] else None,
        }
        client = deps.supabase_admin()
        await _db(
            lambda: (
                client.table("puzzle_attempts")
                .upsert(row, on_conflict="user_id,edition_id")
                .execute()
            )
        )
        if record["correct"]:
            await reading.record_signal(
                user_id, items[q]["edition_article_id"], "puzzle_correct", once=True
            )
    summary = summarize(answers, len(items))
    return {
        "correct": record["correct"],
        "answer": items[q]["answer"],
        "score": summary["score"],
        "done": summary["done"],
    }


async def streak(user_id: str, today: date | None = None) -> int:
    """The reader's current streak of days with a finished puzzle."""
    client = deps.supabase_admin()
    rows = await _db(
        lambda: (
            client.table("puzzle_attempts")
            .select("editions(edition_date)")
            .eq("user_id", user_id)
            .not_.is_("completed_at", "null")
            .execute()
            .data
        )
    )
    days = [
        date.fromisoformat(r["editions"]["edition_date"])
        for r in rows
        if r.get("editions")
    ]
    return streak_from_dates(days, today or datetime.now(UTC).date())


async def card_state(user_id: str, edition_id: str) -> dict | None:
    """What the home page's puzzle card needs, or None when the edition has no puzzle."""
    items = await get_items(edition_id)
    if not items:
        return None
    summary = summarize(await get_attempt(user_id, edition_id), len(items))
    return {**summary, "total": len(items)}
