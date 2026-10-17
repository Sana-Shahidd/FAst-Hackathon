"""Mute keywords: whole words, case-insensitive, Chinese substring, removed count."""

from __future__ import annotations

import pytest

from app.models import Candidate
from app.services.mutes import filter_muted, matching_keyword

pytestmark = pytest.mark.unit


def cand(title: str, summary: str = "", lang: str = "en") -> Candidate:
    return Candidate(
        url=f"https://example.com/{abs(hash(title + summary))}",
        title=title,
        summary=summary,
        lang=lang,
    )


def test_short_keyword_matches_the_word_not_substrings() -> None:
    said = cand("Minister said talks will continue")
    ai = cand("New AI chip announced")
    kept, removed = filter_muted([said, ai], ["ai"], "en")
    assert kept == [said]
    assert removed == 1


def test_matching_is_case_insensitive() -> None:
    items = [
        cand("CRICKET: Pakistan win"),
        cand("Cricket fever"),
        cand("cricketers rest"),
    ]
    kept, removed = filter_muted(items, ["Cricket"], "en")
    assert [c.title for c in kept] == ["cricketers rest"]
    assert removed == 2


def test_summary_is_checked_too() -> None:
    item = cand("Weekend roundup", summary="Plenty of celebrity gossip inside")
    assert filter_muted([item], ["celebrity"], "en") == ([], 1)


def test_phrases_and_punctuation_are_matched_literally() -> None:
    hit = cand("Why the C++ language endures")
    miss = cand("Learning C and Go")
    kept, removed = filter_muted([hit, miss], ["c++"], "en")
    assert kept == [miss]
    assert removed == 1
    assert filter_muted([cand("Formula 1 returns")], ["formula 1"], "en")[1] == 1


def test_chinese_uses_substring_matching() -> None:
    zh = cand("巴基斯坦板球队赢得系列赛", lang="zh")
    other = cand("科技公司发布新产品", lang="zh")
    kept, removed = filter_muted([zh, other], ["板球"], "zh")
    assert kept == [other]
    assert removed == 1
    # a Chinese keyword is a substring match even inside an English-language edition
    assert filter_muted([zh], ["板球"], "en")[1] == 1


def test_urdu_keyword_matches_whole_words() -> None:
    hit = cand("کرکٹ ٹیم کی جیت", lang="ur")
    kept, removed = filter_muted(
        [hit, cand("سیاست کی خبریں", lang="ur")], ["کرکٹ"], "ur"
    )
    assert removed == 1
    assert hit not in kept


def test_blank_keywords_and_empty_inputs_remove_nothing() -> None:
    items = [cand("Anything at all")]
    assert filter_muted(items, ["", "   "], "en") == (items, 0)
    assert filter_muted(items, [], "en") == (items, 0)
    assert filter_muted([], ["ai"], "en") == ([], 0)


def test_matching_keyword_reports_which_word_matched() -> None:
    item = cand("Celebrity wedding and cricket final")
    assert matching_keyword(item, ["politics", "Cricket"], "en") == "Cricket"
    assert matching_keyword(item, ["politics"], "en") is None
