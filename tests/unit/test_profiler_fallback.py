"""Profiler: code fallback split, output validation and agent -> fallback behaviour."""

from __future__ import annotations

import pytest

from app.agents import profiler, runner
from app.models import ParsedInterest, ProfilerOut

pytestmark = pytest.mark.unit


def labels(items: list[ParsedInterest]) -> list[str]:
    return [i.label for i in items]


def test_commas_and_the_word_and_split_the_text() -> None:
    got = profiler.fallback_interests(
        "Pakistani startups, F1 and climate in South Asia"
    )
    assert labels(got) == ["Pakistani startups", "F1", "climate in South Asia"]
    assert got[0].query == '"Pakistani startups"'


def test_urdu_comma_splits() -> None:
    got = profiler.fallback_interests("پاکستانی سٹارٹ اپس، کرکٹ، مصنوعی ذہانت")
    assert labels(got) == ["پاکستانی سٹارٹ اپس", "کرکٹ", "مصنوعی ذہانت"]


def test_urdu_and_arabic_waw_between_words_splits() -> None:
    assert labels(profiler.fallback_interests("کرکٹ و سیاست")) == ["کرکٹ", "سیاست"]
    assert labels(profiler.fallback_interests("الذكاء الاصطناعي و كرة القدم")) == [
        "الذكاء الاصطناعي",
        "كرة القدم",
    ]


def test_a_waw_inside_a_word_is_not_a_separator() -> None:
    assert labels(profiler.fallback_interests("وزارت خارجہ")) == ["وزارت خارجہ"]


def test_at_most_five_interests_and_no_duplicates() -> None:
    text = "a1, b2, c3, d4, e5, f6, g7, A1"
    assert labels(profiler.fallback_interests(text)) == ["a1", "b2", "c3", "d4", "e5"]


def test_blank_and_punctuation_only_text_gives_nothing() -> None:
    assert profiler.fallback_interests("   ") == []
    assert profiler.fallback_interests(" , and , ") == []


def test_clean_strips_dedupes_and_drops_empty_queries() -> None:
    raw = [
        ParsedInterest(label="  AI  ", query="  ai  "),
        ParsedInterest(label="ai", query="duplicate by label"),
        ParsedInterest(label="No query", query="   "),
        ParsedInterest(label="   ", query="empty label"),
        ParsedInterest(label="F1", query='"Formula 1"'),
    ]
    got = profiler.clean(raw)
    assert [(i.label, i.query) for i in got] == [("AI", "ai"), ("F1", '"Formula 1"')]


async def test_agent_output_is_used_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    async def fake(key, factory, input, edition_id, **_):
        seen.update(key=key, input=input)
        return ProfilerOut(
            interests=[ParsedInterest(label="EV market", query='"electric vehicles"')]
        )

    monkeypatch.setattr(runner, "run_agent", fake)
    got, used_fallback = await profiler.parse_interests("electric cars", "en")
    assert (labels(got), used_fallback) == (["EV market"], False)
    assert seen["key"] == "profiler"
    assert (
        "<text>electric cars</text>" in seen["input"]
        and "language: en" in seen["input"]
    )


@pytest.mark.parametrize("agent_result", [None, ProfilerOut(interests=[])])
async def test_failed_or_empty_agent_falls_back_to_the_split(
    monkeypatch: pytest.MonkeyPatch, agent_result: object
) -> None:
    async def fake(*_args, **_kwargs):
        return agent_result

    monkeypatch.setattr(runner, "run_agent", fake)
    got, used_fallback = await profiler.parse_interests("F1, cricket", "en")
    assert (labels(got), used_fallback) == (["F1", "cricket"], True)


async def test_text_is_capped_and_empty_text_skips_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(*_args, **_kwargs):
        raise AssertionError("agent must not run for empty text")

    monkeypatch.setattr(runner, "run_agent", explode)
    assert await profiler.parse_interests("   ", "en") == ([], False)

    captured: list[str] = []

    async def capture(key, factory, input, edition_id, **_):
        captured.append(input)

    monkeypatch.setattr(runner, "run_agent", capture)
    await profiler.parse_interests("x" * 500, "en")
    assert "x" * 200 in captured[0] and "x" * 201 not in captured[0]
