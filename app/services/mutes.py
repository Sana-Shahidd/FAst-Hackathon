"""Mute keywords (F-18): drop candidates containing a muted word before ranking."""

from __future__ import annotations

import re

from app.models import Candidate

_HAN = re.compile("[一-鿿]")


def _matcher(keyword: str, substring: bool) -> re.Pattern[str]:
    escaped = re.escape(keyword)
    if substring:
        return re.compile(escaped, re.IGNORECASE)
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def matching_keyword(cand: Candidate, keywords: list[str], lang: str) -> str | None:
    """The first muted keyword found in the title or summary, else None.

    Matching is case-insensitive and whole-word ("ai" does not mute "said"). Chinese has no
    spaces between words, so Chinese text and Chinese keywords use a plain substring match.
    """
    text = f"{cand.title}\n{cand.summary}"
    chinese_text = (cand.lang or lang) == "zh"
    for raw in keywords:
        keyword = raw.strip()
        if keyword and _matcher(
            keyword, chinese_text or bool(_HAN.search(keyword))
        ).search(text):
            return raw
    return None


def filter_muted(
    cands: list[Candidate], keywords: list[str], lang: str
) -> tuple[list[Candidate], int]:
    """(kept candidates, number removed)."""
    kept = [c for c in cands if matching_keyword(c, keywords, lang) is None]
    return kept, len(cands) - len(kept)
