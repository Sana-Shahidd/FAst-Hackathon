"""Slots and section order for one edition (docs/02_PRD.md F-05 step 5)."""

from __future__ import annotations

from app.models import Pick, PlacedArticle

SECONDARY_COUNT = 3  # PRD: "2-4 secondary"
SLOT_RANK = {"lead": 0, "secondary": 1, "brief": 2}
DEFAULT_WEIGHTS = {"your_city": 0.6, "world": 0.3}


def assign_slots(picks: list[Pick], style: str = "broadsheet") -> list[PlacedArticle]:
    """One `lead` (highest importance), up to 3 `secondary`, the rest `brief`.

    Positions are provisional (slot, then importance); `arrange` finalises them once the
    section order is known. Only the broadsheet style exists (docs/DECISIONS.md).
    """
    ranked = sorted(
        picks, key=lambda p: -p.importance
    )  # stable: ties keep the picker's order
    placed: list[PlacedArticle] = []
    for index, pick in enumerate(ranked):
        if index == 0:
            slot = "lead"
        elif index <= SECONDARY_COUNT:
            slot = "secondary"
        else:
            slot = "brief"
        placed.append(
            PlacedArticle(
                candidate_id=pick.candidate_id,
                section=pick.section,
                slot=slot,
                position=index,
                importance=pick.importance,
                reason=pick.reason,
            )
        )
    return placed


def order_sections(picks: list[Pick], weights: dict[str, float]) -> list[str]:
    """Section keys, the reader's strongest interests first (ties: highest importance)."""
    best: dict[str, int] = {}
    for pick in picks:
        best[pick.section] = max(best.get(pick.section, 0), pick.importance)

    def key(section: str) -> tuple[float, int, str]:
        weight = weights.get(section, DEFAULT_WEIGHTS.get(section, 0.5))
        return (-weight, -best[section], section)

    return sorted(best, key=key)


def arrange(
    placed: list[PlacedArticle], section_order: list[str]
) -> list[PlacedArticle]:
    """Final reading order: the lead, then each section in order (secondary before brief)."""
    rank = {section: i for i, section in enumerate(section_order)}
    ordered = sorted(
        placed,
        key=lambda p: (
            p.slot != "lead",
            rank.get(p.section, len(rank)),
            SLOT_RANK[p.slot],
            -p.importance,
        ),
    )
    return [p.model_copy(update={"position": i}) for i, p in enumerate(ordered)]
