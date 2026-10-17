"""Puzzle items: valid Editor items kept, invalid replaced, fallback rules, always 5."""

from __future__ import annotations

import pytest

from app.models import EditorOut, PlacedArticle, PuzzleItem
from app.services import puzzle

pytestmark = pytest.mark.unit

HEADLINES = {
    "a1": "Pakistan defeat Australia by six wickets in Lahore",
    "a2": "Government announces new startup policy for technology founders",
    "a3": "Floods displace thousands across northern regions overnight",
    "a4": "Electric vehicle sales double as battery prices keep falling",
    "a5": "Scientists discover ancient river system beneath Antarctic ice",
    "a6": "Central bank holds interest rates steady amid inflation worries",
}


def placed(ids=None) -> list[PlacedArticle]:
    ids = ids or list(HEADLINES)
    return [
        PlacedArticle(
            candidate_id=cid, section="world", slot="brief", position=i, importance=5
        )
        for i, cid in enumerate(ids)
    ]


def editor_out(*items: PuzzleItem) -> EditorOut:
    return EditorOut(
        lead_headline="L",
        lead_dek="D",
        articles=[],
        three_things=["a", "b", "c"],
        puzzle=list(items),
    )


def good_item(
    cid: str = "a1", answer: str = "Australia", decoys=("India", "England", "Zimbabwe")
) -> PuzzleItem:
    return PuzzleItem(
        candidate_id=cid,
        masked_headline=HEADLINES[cid].replace(answer, "___", 1),
        answer=answer,
        decoys=list(decoys),
    )


def test_valid_editor_items_are_kept_with_four_unique_choices() -> None:
    items = puzzle.items_from_editor(editor_out(good_item()), placed(), HEADLINES, "en")
    first = items[0]
    assert (first["candidate_id"], first["answer"]) == ("a1", "Australia")
    assert first["masked_headline"] == "Pakistan defeat ___ by six wickets in Lahore"
    assert len(first["choices"]) == 4 and len(set(first["choices"])) == 4
    assert set(first["choices"]) == {"Australia", "India", "England", "Zimbabwe"}


def test_there_are_always_five_items() -> None:
    assert (
        len(
            puzzle.items_from_editor(editor_out(good_item()), placed(), HEADLINES, "en")
        )
        == 5
    )
    assert len(puzzle.items_from_editor(None, placed(), HEADLINES, "en")) == 5
    assert len(puzzle.items_from_editor(editor_out(), placed(), HEADLINES, "en")) == 5


def test_each_article_appears_at_most_once() -> None:
    twin = good_item(answer="Pakistan", decoys=("India", "Nepal", "Oman"))
    items = puzzle.items_from_editor(
        editor_out(good_item(), twin), placed(), HEADLINES, "en"
    )
    ids = [i["candidate_id"] for i in items]
    assert len(ids) == len(set(ids)) == 5
    assert items[0]["answer"] == "Australia"  # the first valid item for a1 wins


@pytest.mark.parametrize(
    "bad",
    [
        PuzzleItem(
            candidate_id="a1",
            masked_headline="Pakistan defeat ___ by six wickets in Lahore",
            answer="Australia",
            decoys=["India", "Australia", "Oman"],
        ),
        PuzzleItem(
            candidate_id="a1",
            masked_headline="Pakistan beat ___ by six wickets in Lahore",
            answer="Australia",
            decoys=["India", "England", "Oman"],
        ),
        PuzzleItem(
            candidate_id="a1",
            masked_headline="Pakistan defeat Australia by six wickets in Lahore",
            answer="Australia",
            decoys=["India", "England", "Oman"],
        ),
        PuzzleItem(
            candidate_id="a1",
            masked_headline="Pakistan defeat ___ by ___ wickets in Lahore",
            answer="Australia",
            decoys=["India", "England", "Oman"],
        ),
        PuzzleItem(
            candidate_id="a1",
            masked_headline="Pakistan defeat ___ by six wickets in Lahore",
            answer="Australia",
            decoys=["India", "india", "Oman"],
        ),
        PuzzleItem(
            candidate_id="a1",
            masked_headline="Pakistan defeat ___ by six wickets in Lahore",
            answer="Australia",
            decoys=["India", "", "Oman"],
        ),
        PuzzleItem(
            candidate_id="ghost",
            masked_headline="x ___ y",
            answer="z",
            decoys=["a", "b", "c"],
        ),
    ],
    ids=[
        "answer-in-decoys",
        "headline-mismatch",
        "no-blank",
        "two-blanks",
        "duplicate-decoys",
        "empty-decoy",
        "unknown-article",
    ],
)
def test_invalid_editor_items_are_replaced_by_fallback_items(bad: PuzzleItem) -> None:
    items = puzzle.items_from_editor(editor_out(bad), placed(), HEADLINES, "en")
    assert len(items) == 5
    assert all(i["masked_headline"].count("___") == 1 for i in items)
    for item in items:
        restored = item["masked_headline"].replace("___", item["answer"], 1)
        assert (
            restored == HEADLINES[item["candidate_id"]]
        )  # always reproduces the real headline
    assert items[0]["choices"] != ["Australia", "India", "Oman"]


def test_fallback_hides_the_longest_non_stopword_of_at_least_four_letters() -> None:
    items = puzzle.fallback_items(placed(), HEADLINES, "en")
    by_id = {i["candidate_id"]: i for i in items}
    assert by_id["a1"]["answer"] == "Australia"
    assert (
        by_id["a2"]["answer"] == "Government"
    )  # 10 letters, ties between equal lengths keep the first
    stop = puzzle.stopwords("en")
    for item in items:
        assert len(item["answer"]) >= 4 and item["answer"].lower() not in stop


def test_fallback_decoys_are_similar_length_words_from_other_headlines() -> None:
    (item,) = puzzle.fallback_items(placed(["a1", "a2", "a3"]), HEADLINES, "en", n=1)
    others = " ".join(HEADLINES[c] for c in ("a2", "a3")).lower()
    decoys = [c for c in item["choices"] if c != item["answer"]]
    assert len(decoys) == 3 and len({d.lower() for d in decoys}) == 3
    for d in decoys:
        assert d.lower() in others
        assert abs(len(d) - len(item["answer"])) <= 4
    assert item["answer"] in item["choices"]


def test_fallback_is_deterministic() -> None:
    assert puzzle.fallback_items(placed(), HEADLINES, "en") == puzzle.fallback_items(
        placed(), HEADLINES, "en"
    )


def test_the_hidden_word_is_matched_as_a_whole_word() -> None:
    assert (
        puzzle.mask("The Pakistani team and Pakistan fans", "Pakistan", "en")
        == "The Pakistani team and ___ fans"
    )
    assert puzzle.mask("Nothing here", "Pakistan", "en") is None


def test_chinese_hides_a_two_character_span() -> None:
    headlines = {
        "z1": "巴基斯坦板球队赢得系列赛",
        "z2": "科技公司发布新产品引发关注",
        "z3": "气候大会达成新的减排协议",
        "z4": "国际油价连续第三周下跌",
        "z5": "电动汽车销量继续大幅增长",
    }
    pl = [
        PlacedArticle(
            candidate_id=k, section="world", slot="brief", position=i, importance=5
        )
        for i, k in enumerate(headlines)
    ]
    items = puzzle.fallback_items(pl, headlines, "zh")
    assert len(items) == 5
    for item in items:
        assert len(item["answer"]) == 2 and item["masked_headline"].count("___") == 1
        assert (
            item["masked_headline"].replace("___", item["answer"], 1)
            == headlines[item["candidate_id"]]
        )
        assert all(len(c) == 2 for c in item["choices"])


def test_urdu_headlines_work_too() -> None:
    headlines = {
        "u1": "پاکستان نے آسٹریلیا کو چھ وکٹوں سے شکست دے دی",
        "u2": "حکومت نے نئی ٹیکنالوجی پالیسی کا اعلان کر دیا",
        "u3": "شمالی علاقوں میں سیلاب سے ہزاروں افراد متاثر",
        "u4": "مرکزی بینک نے شرح سود برقرار رکھی ہے",
        "u5": "سائنسدانوں نے قدیم دریائی نظام دریافت کر لیا",
    }
    pl = [
        PlacedArticle(
            candidate_id=k, section="world", slot="brief", position=i, importance=5
        )
        for i, k in enumerate(headlines)
    ]
    items = puzzle.fallback_items(pl, headlines, "ur")
    assert len(items) == 5
    for item in items:
        assert (
            item["masked_headline"].replace("___", item["answer"], 1)
            == headlines[item["candidate_id"]]
        )
        assert len(item["answer"]) >= 4 and item[
            "answer"
        ].lower() not in puzzle.stopwords("ur")


def test_too_few_headlines_give_fewer_items_rather_than_garbage() -> None:
    few = {"a1": HEADLINES["a1"]}
    assert (
        puzzle.items_from_editor(None, placed(["a1"]), few, "en") == []
    )  # no other headlines for decoys


def test_choices_are_shuffled_but_stable_per_article() -> None:
    first = puzzle.items_from_editor(
        editor_out(good_item()), placed(), HEADLINES, "en"
    )[0]
    again = puzzle.items_from_editor(
        editor_out(good_item()), placed(), HEADLINES, "en"
    )[0]
    assert first["choices"] == again["choices"]
