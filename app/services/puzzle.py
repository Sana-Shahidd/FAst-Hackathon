"""Headline puzzle ("Fill the headline", F-17): build, validate and pad items.

Stored items look like `{"candidate_id", "masked_headline", "answer", "choices": [4]}`; the
pipeline swaps `candidate_id` for `edition_article_id` when it saves them. Grading and
streaks arrive with the puzzle page (T-11).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from functools import cache

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
