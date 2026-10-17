"""Ask Subah through the real route: paper + live news search, the Answerer, fallback, limits (F-24)."""

from __future__ import annotations

import html as htmllib

import httpx
import pytest
from fastapi.testclient import TestClient

from app import deps
from app.agents import runner
from app.main import app
from app.models import AnswerOut
from app.services import i18n

pytestmark = pytest.mark.integration


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/login")
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def ask(client: TestClient, question: str):
    return client.post("/ask", data={"q": question}, headers=csrf(client))


def set_headline(admin, art: dict, text: str) -> None:
    admin.table("edition_articles").update(
        {"headline": text, "summary": f"{text} says the report."}
    ).eq("id", art["id"]).execute()


def live_feed(feeds_mock, *items: tuple[str, str]) -> list[dict]:
    """Make the Google News search return these (title, url) items; returns the requests seen."""
    from tests.conftest import rss

    def search(request: httpx.Request) -> httpx.Response:
        body = rss([t for t, _ in items], "Live Wire")
        for title, url in items:
            body = body.replace("https://news.example.com/", url, 1) if False else body
        return httpx.Response(200, text=body)

    feeds_mock.get("https://news.google.com/rss/search").mock(side_effect=search)
    return []


def test_the_home_page_has_the_ask_box(client: TestClient, edition) -> None:
    home = htmllib.unescape(client.get("/paper/today").text)
    assert 'hx-post="/ask"' in home and 'name="q"' in home and 'id="ask-result"' in home
    assert i18n.t("ask.title", "en") in home and i18n.t("ask.placeholder", "en") in home


def test_a_question_is_answered_from_the_matching_stories_with_citations(
    client: TestClient, edition, admin, monkeypatch, fake_agents
) -> None:
    art = next(a for a in edition["articles"] if a["slot"] != "lead")
    set_headline(admin, art, "Central bank holds interest rates steady")
    seen: dict = {}

    async def run(key, factory, prompt, edition_id, **kwargs):
        if key == "answerer":
            seen["prompt"] = prompt
            return AnswerOut(answer="The central bank kept rates unchanged.", used=[1])
        return await fake_agents(key, factory, prompt, edition_id, **kwargs)

    monkeypatch.setattr(runner, "run_agent", run)
    response = ask(client, "What did the central bank do about interest rates?")
    assert response.status_code == 200 and "<html" not in response.text
    text = htmllib.unescape(response.text)
    assert "The central bank kept rates unchanged." in text
    assert (
        f'href="/r/{art["id"]}"' in response.text
    )  # the paper's story links through /r/{id}
    assert "Central bank holds interest rates steady" in text
    assert i18n.t("ask.sources", "en") in text
    assert (
        "<question>" in seen["prompt"]
        and "Central bank holds interest rates steady" in seen["prompt"]
    )
    assert "@" not in seen["prompt"] and "edition_language: en" in seen["prompt"]


def test_live_news_results_are_searched_too_and_linked_safely(
    client: TestClient, edition, feeds_mock, monkeypatch, fake_agents
) -> None:
    from tests.conftest import rss

    def search(request: httpx.Request) -> httpx.Response:
        text = rss(["Solar exports double across the Gulf region"], "Gulf Wire")
        return httpx.Response(200, text=text)

    feeds_mock.get("https://news.google.com/rss/search").mock(side_effect=search)

    async def run(key, factory, prompt, edition_id, **kwargs):
        if key == "answerer":
            assert "Solar exports double" in prompt
            return AnswerOut(answer="Solar exports doubled.", used=[1])
        return await fake_agents(key, factory, prompt, edition_id, **kwargs)

    monkeypatch.setattr(runner, "run_agent", run)
    response = ask(client, "solar exports gulf")
    text = htmllib.unescape(response.text)
    assert "Solar exports doubled." in text and "Gulf Wire" in text
    assert (
        'rel="noopener noreferrer"' in response.text
        and 'href="https://news.example.com/' in response.text
    )


def test_without_the_assistant_the_closest_stories_are_shown_instead(
    client: TestClient, edition, admin, monkeypatch
) -> None:
    art = next(a for a in edition["articles"] if a["slot"] != "lead")
    set_headline(admin, art, "Floods ease across northern regions")

    async def down(*_a, **_k):
        return None

    monkeypatch.setattr(runner, "run_agent", down)
    response = ask(client, "floods northern regions")
    text = htmllib.unescape(response.text)
    assert (
        i18n.t("ask.fallback_note", "en") in text
        and "Floods ease across northern regions" in text
    )
    assert f'href="/r/{art["id"]}"' in response.text


def test_a_question_nothing_matches_says_so_without_calling_the_model(
    client: TestClient, edition, monkeypatch
) -> None:
    async def never(key, *a, **k):
        assert key != "answerer", "the model must not be called when no story matches"

    monkeypatch.setattr(runner, "run_agent", never)
    response = ask(client, "zxqv wibble frobnicate")
    assert htmllib.unescape(i18n.t("ask.none", "en")) in htmllib.unescape(response.text)


def test_a_model_that_cites_nothing_still_shows_the_closest_stories(
    client: TestClient, edition, admin, monkeypatch, fake_agents
) -> None:
    art = next(a for a in edition["articles"] if a["slot"] != "lead")
    set_headline(admin, art, "Battery plant opens in Punjab")

    async def run(key, factory, prompt, edition_id, **kwargs):
        if key == "answerer":
            return AnswerOut(answer="The articles do not say.", used=[])
        return await fake_agents(key, factory, prompt, edition_id, **kwargs)

    monkeypatch.setattr(runner, "run_agent", run)
    text = htmllib.unescape(ask(client, "battery plant punjab").text)
    assert (
        "The articles do not say." in text and "Battery plant opens in Punjab" in text
    )


def test_hostile_article_text_cannot_inject_markup_into_the_answer_box(
    client: TestClient, edition, admin, monkeypatch, fake_agents
) -> None:
    art = next(a for a in edition["articles"] if a["slot"] != "lead")
    set_headline(admin, art, "<script>alert(1)</script> central bank")

    async def run(key, factory, prompt, edition_id, **kwargs):
        if key == "answerer":
            return AnswerOut(answer="<img src=x onerror=alert(1)> done", used=[1])
        return await fake_agents(key, factory, prompt, edition_id, **kwargs)

    monkeypatch.setattr(runner, "run_agent", run)
    response = ask(client, "central bank")
    assert "<script>" not in response.text and "<img" not in response.text


def test_questions_are_validated_trimmed_rate_limited_and_private(
    client: TestClient, edition, monkeypatch, make_user, post_form
) -> None:
    async def down(*_a, **_k):
        return None

    monkeypatch.setattr(runner, "run_agent", down)
    assert ask(client, "ab").status_code == 422
    assert client.post("/ask", data={"q": "central bank"}).status_code == 403
    anonymous = TestClient(app)
    response = anonymous.post(
        "/ask",
        data={"q": "central bank"},
        headers={**csrf(anonymous), "HX-Request": "true"},
    )
    assert response.status_code == 401
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    assert (
        browser.post(
            "/ask", data={"q": "central bank"}, headers=csrf(browser)
        ).status_code
        == 404
    )
    assert (
        ask(client, "x" * 500).status_code == 200
    )  # an over-long question is trimmed, not an error
    codes = [ask(client, "central bank rates").status_code for _ in range(12)]
    assert 429 in codes and codes[0] == 200
