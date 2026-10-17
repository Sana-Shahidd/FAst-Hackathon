"""Run an agent on its primary model, then the fallback model, else None (docs/06 §2)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from agents import Agent, Runner

from app.agents.llm import build_model
from app.config import AGENT_TIMEOUT_S, settings
from app.services import activity


async def run_agent(
    key: str,
    factory: Callable[[Any], Agent],
    input: str,
    edition_id: str | None,
    *,
    timeout_s: float = AGENT_TIMEOUT_S,
) -> object | None:
    """Typed output from the first model that works; None means "use the code fallback"."""
    for spec in (settings.model_for(key), settings.FALLBACK_MODEL):
        provider = spec.split(":")[0]
        t0 = time.monotonic()
        try:
            agent = factory(build_model(spec))
            result = await asyncio.wait_for(
                Runner.run(agent, input, max_turns=1), timeout_s
            )
        except Exception as exc:  # noqa: BLE001 - any failure moves to the next model
            await activity.log(
                edition_id, key, "fallback", f"{provider} failed: {type(exc).__name__}"
            )
            continue
        ms = int((time.monotonic() - t0) * 1000)
        await activity.log(
            edition_id, key, "finished", f"{key} done with {provider}", {"ms": ms}
        )
        return result.final_output
    return None
