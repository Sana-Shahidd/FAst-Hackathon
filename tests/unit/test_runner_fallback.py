"""primary model error -> fallback model; both fail -> None; activity rows written."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents import runner
from app.config import settings

pytestmark = pytest.mark.unit


@pytest.fixture
def rows(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    logged: list[tuple] = []

    async def fake_log(edition_id, agent, kind, message, data=None):
        logged.append((edition_id, agent, kind, message, data))

    monkeypatch.setattr(runner.activity, "log", fake_log)
    monkeypatch.setattr(settings, "CURATOR_MODEL", "gemini:primary-id")
    monkeypatch.setattr(settings, "FALLBACK_MODEL", "groq:fallback-id")
    monkeypatch.setattr(runner, "build_model", lambda spec: spec)
    return logged


def _factory(model):
    return model


def _fake_run(outcomes: dict[str, object]):
    async def run(agent, input, max_turns):
        outcome = outcomes[agent]
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(final_output=outcome)

    return run


async def test_primary_success_does_not_touch_fallback(monkeypatch, rows) -> None:
    monkeypatch.setattr(
        runner.Runner, "run", _fake_run({"gemini:primary-id": "picked"}), raising=False
    )
    assert await runner.run_agent("curator", _factory, "in", "ed-1") == "picked"
    assert [r[2] for r in rows] == ["finished"]
    assert rows[0][:2] == ("ed-1", "curator")
    assert "gemini" in rows[0][3]
    assert rows[0][4]["ms"] >= 0


async def test_primary_error_falls_back_to_second_model(monkeypatch, rows) -> None:
    outcomes = {
        "gemini:primary-id": RuntimeError("429"),
        "groq:fallback-id": "from-groq",
    }
    monkeypatch.setattr(runner.Runner, "run", _fake_run(outcomes), raising=False)
    assert await runner.run_agent("curator", _factory, "in", None) == "from-groq"
    assert [r[2] for r in rows] == ["fallback", "finished"]
    assert rows[0][3] == "gemini failed: RuntimeError"
    assert "groq" in rows[1][3]


async def test_both_models_fail_returns_none(monkeypatch, rows) -> None:
    outcomes = {
        "gemini:primary-id": RuntimeError("x"),
        "groq:fallback-id": ValueError("y"),
    }
    monkeypatch.setattr(runner.Runner, "run", _fake_run(outcomes), raising=False)
    assert await runner.run_agent("curator", _factory, "in", "ed-2") is None
    assert [r[2] for r in rows] == ["fallback", "fallback"]
    assert [r[3] for r in rows] == [
        "gemini failed: RuntimeError",
        "groq failed: ValueError",
    ]


async def test_timeout_counts_as_failure(monkeypatch, rows) -> None:
    import asyncio

    async def slow(agent, input, max_turns):
        await asyncio.sleep(5)

    monkeypatch.setattr(runner.Runner, "run", slow, raising=False)
    assert (
        await runner.run_agent("curator", _factory, "in", None, timeout_s=0.01) is None
    )
    assert rows[0][3] == "gemini failed: TimeoutError"


async def test_unconfigured_model_is_a_failure_not_a_crash(monkeypatch, rows) -> None:
    monkeypatch.setattr(
        runner, "build_model", __import__("app.agents.llm", fromlist=["x"]).build_model
    )
    monkeypatch.setattr(settings, "CURATOR_MODEL", "gemini:<flash-id>")
    monkeypatch.setattr(settings, "FALLBACK_MODEL", "")
    assert await runner.run_agent("curator", _factory, "in", None) is None
    assert [r[2] for r in rows] == ["fallback", "fallback"]
    assert rows[0][3] == "gemini failed: ValueError"
