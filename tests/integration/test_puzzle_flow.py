"""Playing the headline puzzle end to end (T-11: F-17): questions, grading, score, streak, learning."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.main import app
from app.services import i18n

pytestmark = pytest.mark.integration


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/login")
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def items(admin, edition_id: str) -> list[dict]:
    return (
        admin.table("puzzles")
        .select("items")
        .eq("edition_id", edition_id)
        .execute()
        .data[0]["items"]
    )


def answer(client: TestClient, q: int, choice: str, day: str = "today"):
    return client.post(
        f"/puzzle/{day}/answer", data={"q": q, "choice": choice}, headers=csrf(client)
    )


def attempt(admin, user_id: str) -> dict | None:
    rows = (
        admin.table("puzzle_attempts").select("*").eq("user_id", user_id).execute().data
    )
    return rows[0] if rows else None


def wrong_choice(item: dict) -> str:
    return next(c for c in item["choices"] if c != item["answer"])


def test_the_puzzle_page_shows_the_first_question_with_four_choices(
    client: TestClient, edition, admin
) -> None:
    quiz = items(admin, edition["id"])
    assert len(quiz) == 5
    page = client.get("/puzzle/today")
    assert page.status_code == 200
    html = page.text
    assert i18n.t("puzzle.title", "en").replace("'", "&#39;") in html
    assert i18n.t("puzzle.question", "en", n=1, total=5) in html
    assert (
        'class="blank"' in html and "___" not in html
    )  # the gap is drawn, not printed
    for choice in quiz[0]["choices"]:
        assert f'value="{choice}"' in html
    assert html.count('class="choice"') == 4
    assert client.get(f"/puzzle/{edition['day']}").status_code == 200  # by date too


def test_a_full_game_scores_saves_the_attempt_and_shows_the_streak(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    quiz = items(admin, edition["id"])
    for q, item in enumerate(quiz):
        choice = item["answer"] if q < 3 else wrong_choice(item)
        response = answer(client, q, choice)
        assert response.status_code == 200 and "<html" not in response.text
        reveal = response.text
        if q < 3:
            assert i18n.t("puzzle.correct", "en") in reveal and "is-right" in reveal
        else:
            assert "is-wrong" in reveal
            assert (
                f"/r/{item['edition_article_id']}" in reveal
            )  # the full headline links to the story
        assert (
            i18n.t("puzzle.see_score", "en") if q == 4 else i18n.t("puzzle.next", "en")
        ) in reveal
    saved = attempt(admin, onboarded_user.id)
    assert saved["score"] == 3 and saved["completed_at"] is not None
    assert [a["correct"] for a in saved["answers"]] == [True, True, True, False, False]

    finale = client.get("/puzzle/today", headers={"HX-Request": "true"}).text
    assert "3/5" in finale and i18n.t("puzzle.score", "en", score=3) in finale
    assert i18n.t("puzzle.streak", "en", n=1) in finale
    assert i18n.t("puzzle.read_stories", "en") in finale
    for item in quiz:
        assert f"/r/{item['edition_article_id']}" in finale
    full_page = client.get("/puzzle/today").text
    assert "<html" in full_page and i18n.t("puzzle.streak", "en", n=1) in full_page


def test_each_question_is_graded_once_and_the_first_answer_stands(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    quiz = items(admin, edition["id"])
    answer(client, 0, wrong_choice(quiz[0]))
    again = answer(client, 0, quiz[0]["answer"])  # trying to fix it
    assert again.status_code == 200 and "is-wrong" in again.text
    saved = attempt(admin, onboarded_user.id)
    assert len(saved["answers"]) == 1 and saved["answers"][0]["correct"] is False
    assert saved["completed_at"] is None  # not finished yet
    resumed = client.get("/puzzle/today").text
    assert (
        i18n.t("puzzle.question", "en", n=2, total=5) in resumed
    )  # continues where it stopped


def test_right_answers_raise_the_stories_interest_by_the_puzzle_weight_once(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    quiz = items(admin, edition["id"])
    topic = "pakistan"
    for item in quiz[:2]:  # make the first two questions about a followed topic
        admin.table("edition_articles").update(
            {"topic_key": topic, "interest_id": None}
        ).eq("id", item["edition_article_id"]).execute()
    q, item = 0, quiz[0]

    def weight() -> float:
        rows = (
            admin.table("interests")
            .select("weight")
            .eq("user_id", onboarded_user.id)
            .eq("topic_key", topic)
            .execute()
            .data
        )
        return rows[0]["weight"]

    before = weight()
    answer(client, q, wrong_choice(item))
    assert weight() == before  # a wrong answer teaches nothing
    answer(client, 1, quiz[1]["answer"])
    assert weight() == round(before + 0.03, 2)
    kinds = (
        admin.table("signals")
        .select("kind")
        .eq("user_id", onboarded_user.id)
        .eq("kind", "puzzle_correct")
        .execute()
        .data
    )
    assert len(kinds) == 1


def test_bad_questions_and_choices_are_rejected_without_saving(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    assert answer(client, 7, "beat").status_code == 422
    assert answer(client, -1, "beat").status_code == 422
    assert answer(client, 0, "definitely not a choice").status_code == 422
    assert (
        client.post("/puzzle/today/answer", data={"q": 0, "choice": "x"}).status_code
        == 403
    )
    assert attempt(admin, onboarded_user.id) is None


def test_missing_editions_dates_and_strangers_get_nothing(
    client: TestClient, edition, admin, make_user, post_form
) -> None:
    assert client.get("/puzzle/2001-01-01").status_code == 404
    assert client.get("/puzzle/not-a-date").status_code == 404
    assert answer(client, 0, "x", "2001-01-01").status_code == 404
    anonymous = TestClient(app).get("/puzzle/today", follow_redirects=False)
    assert (anonymous.status_code, anonymous.headers["location"]) == (303, "/login")
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    assert (
        browser.get("/puzzle/today", follow_redirects=False).headers["location"]
        == "/onboarding"
    )
    assert (
        browser.get(f"/puzzle/{edition['day']}", follow_redirects=False).status_code
        == 303
    )


def test_the_home_page_offers_the_puzzle_and_remembers_the_score(
    client: TestClient, edition, admin
) -> None:
    home = client.get("/paper/today").text
    assert 'class="puzzle-card"' in home and 'href="/puzzle/today"' in home
    assert (
        i18n.t("puzzle.subtitle", "en") in home and i18n.t("puzzle.play", "en") in home
    )
    for q, item in enumerate(items(admin, edition["id"])):
        answer(client, q, item["answer"])
    done = client.get("/paper/today").text
    assert i18n.t("puzzle.score", "en", score=5) in done


def test_a_streak_needs_finished_days_in_a_row(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    import asyncio
    from datetime import date, timedelta

    from app.services import edition as pipeline
    from app.services import puzzle

    quiz = items(admin, edition["id"])
    for q, item in enumerate(quiz):
        answer(client, q, item["answer"])
    today = date.fromisoformat(edition["day"])
    assert asyncio.run(puzzle.streak(onboarded_user.id, today)) == 1
    assert (
        asyncio.run(puzzle.streak(onboarded_user.id, today + timedelta(days=1))) == 1
    )  # still alive
    assert (
        asyncio.run(puzzle.streak(onboarded_user.id, today + timedelta(days=2))) == 0
    )  # broken
    yesterday = today - timedelta(days=1)
    old_id = asyncio.run(pipeline.generate_edition(onboarded_user.id, yesterday))
    for q, item in enumerate(items(admin, old_id)):
        client.post(
            f"/puzzle/{yesterday}/answer",
            data={"q": q, "choice": item["answer"]},
            headers=csrf(client),
        )
    assert asyncio.run(puzzle.streak(onboarded_user.id, today)) == 2
