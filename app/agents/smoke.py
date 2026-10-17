"""`python -m app.agents.smoke`: one typed call per configured model (docs/03_TECH.md §6)."""

from __future__ import annotations

import asyncio
import sys

from agents import Agent, AgentOutputSchema, ModelSettings, Runner
from pydantic import BaseModel

from app.agents.llm import build_model
from app.config import settings


class SmokeOut(BaseModel):
    word: str


async def check(spec: str) -> str | None:
    """None when `spec` returns a typed answer, else a short error description."""
    try:
        agent = Agent(
            name="smoke",
            instructions="Return the single word 'ok' in the field 'word'.",
            model=build_model(spec),
            model_settings=ModelSettings(temperature=0.0),
            output_type=AgentOutputSchema(SmokeOut, strict_json_schema=False),
        )
        result = await asyncio.wait_for(Runner.run(agent, "ping", max_turns=1), 30)
        if not isinstance(result.final_output, SmokeOut):
            return f"unexpected output {type(result.final_output).__name__}"
    except Exception as exc:  # noqa: BLE001 - report any failure
        return f"{type(exc).__name__}: {str(exc)[:160]}"
    return None


async def main() -> int:
    specs = {
        "profiler": settings.PROFILER_MODEL,
        "curator": settings.CURATOR_MODEL,
        "editor": settings.EDITOR_MODEL,
        "learner": settings.LEARNER_MODEL,
        "fallback": settings.FALLBACK_MODEL,
    }
    failed = 0
    for spec in dict.fromkeys(specs.values()):
        roles = ",".join(role for role, value in specs.items() if value == spec)
        error = await check(spec)
        failed += error is not None
        print(
            f"{'ok  ' if error is None else 'FAIL'} {spec or '(empty)'} [{roles}]"
            + (f" - {error}" if error else "")
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
