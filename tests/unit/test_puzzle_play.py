"""Puzzle gameplay without a database: grading, idempotence, scoring, streaks and headline helpers."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services import puzzle

pytestmark = pytest.mark.unit

ITEMS = [
    {
        "edition_article_id": f"ea{i}",
        "masked_headline": f"Pakistan ___ India by {i} wickets",
        "answer": "beat",
        "choices": ["beat", "lose", "draw", "tie"],
    }
    for i in range(5)
]


def test_a_right_choice_is_correct_and_a_wrong_one_is_not() -> None:
    right, is_new = puzzle.check(ITEMS, [], 0, "beat")
    wrong, _ = puzzle.check(ITEMS, [], 1, "lose")
    assert (right, is_new) == ({"q": 0, "choice": "beat", "correct": True}, True)
    assert wrong["correct"] is False and wrong["choice"] == "lose"


def test_answering_a_question_twice_keeps_the_first_answer() -> None:
    first, _ = puzzle.check(ITEMS, [], 2, "lose")
    again, is_new = puzzle.check(ITEMS, [first], 2, "beat")
    assert is_new is False and again == first  # no second chance


@pytest.mark.parametrize("q", [-1, 5, 99])
def test_a_question_out_of_range_is_rejected(q: int) -> None:
    with pytest.raises(ValueError):
        puzzle.check(ITEMS, [], q, "beat")


def test_a_choice_that_is_not_offered_is_rejected() -> None:
    with pytest.raises(ValueError):
        puzzle.check(ITEMS, [], 0, "demolish")


def test_the_summary_counts_score_progress_and_the_next_question() -> None:
    answers = [
        {"q": 0, "choice": "beat", "correct": True},
        {"q": 1, "choice": "lose", "correct": False},
        {"q": 3, "choice": "beat", "correct": True},
    ]
    summary = puzzle.summarize(answers, 5)
    assert summary == {"answered": 3, "score": 2, "done": False, "next_q": 2}


def test_the_puzzle_is_done_after_the_last_answer() -> None:
    answers = [{"q": q, "choice": "beat", "correct": q % 2 == 0} for q in range(5)]
    summary = puzzle.summarize(answers, 5)
    assert (summary["done"], summary["score"], summary["next_q"]) == (True, 3, None)
    assert puzzle.summarize([], 5)["next_q"] == 0
    assert puzzle.summarize([], 0)["done"] is False  # no puzzle is never "done"


TODAY = date(2026, 10, 17)


def days(*offsets: int) -> list[date]:
    return [TODAY - timedelta(days=o) for o in offsets]


@pytest.mark.parametrize(
    ("finished", "expected"),
    [
        ([], 0),
        (days(0), 1),
        (days(0, 1, 2), 3),
        (days(1, 2), 2),  # today is not played yet: the streak is still alive
        (days(2, 3), 0),  # a day was missed
        (days(0, 2, 3), 1),  # a gap ends the run
        (days(0, 0, 1), 2),  # duplicates do not double count
    ],
)
def test_streak_counts_consecutive_finished_days(
    finished: list[date], expected: int
) -> None:
    assert puzzle.streak_from_dates(finished, TODAY) == expected


def test_the_full_headline_is_restored_and_the_blank_can_be_underlined() -> None:
    item = ITEMS[3]
    assert puzzle.restore(item) == "Pakistan beat India by 3 wickets"
    assert puzzle.split_blank(item) == ("Pakistan ", " India by 3 wickets")
