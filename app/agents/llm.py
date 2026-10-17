"""Model setup for the openai-agents SDK on Gemini and Groq (docs/06_AGENTS.md §1)."""

from __future__ import annotations

from functools import cache

from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from app.config import settings

set_tracing_disabled(True)

_ENDPOINTS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
}


def parse_spec(spec: str) -> tuple[str, str]:
    """Split `provider:model_id`, rejecting empty values and `<placeholder>` ids."""
    provider, sep, model_id = spec.partition(":")
    if not sep or provider not in _ENDPOINTS or not model_id or "<" in model_id:
        raise ValueError(
            f"invalid model spec {spec!r}; expected 'gemini:<id>' or 'groq:<id>'"
        )
    return provider, model_id


@cache
def _client(provider: str) -> AsyncOpenAI:
    key = {"gemini": settings.GEMINI_API_KEY, "groq": settings.GROQ_API_KEY}[provider]
    if not key:
        raise RuntimeError(f"{provider.upper()}_API_KEY is not set")
    return AsyncOpenAI(base_url=_ENDPOINTS[provider], api_key=key)


def build_model(spec: str) -> OpenAIChatCompletionsModel:
    """Chat-completions model for a `provider:model_id` spec (ids come from env only)."""
    provider, model_id = parse_spec(spec)
    return OpenAIChatCompletionsModel(model=model_id, openai_client=_client(provider))
