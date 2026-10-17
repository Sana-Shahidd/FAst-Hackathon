"""Slots, section order and reading positions."""

from __future__ import annotations

import pytest

from app.models import Pick
from app.services import layout

pytestmark = pytest.mark.unit


def picks(*spec: tuple[str, str, int]) -> list[Pick]:
    return [
        Pick(candidate_id=cid, section=section, importance=imp, reason="r")
        for cid, section, imp in spec
    ]


SAMPLE = picks(
    ("a", "ai", 7),
    ("b", "ai", 10),
    ("c", "pakistan", 8),
    ("d", "world", 6),
    ("e", "pakistan", 9),
    ("f", "ai", 5),
    ("g", "climate", 4),
)


def test_one_lead_three_secondary_and_the_rest_are_briefs() -> None:
    placed = layout.assign_slots(SAMPLE)
    slots = {p.candidate_id: p.slot for p in placed}
    assert slots["b"] == "lead"
    assert sorted(k for k, v in slots.items() if v == "secondary") == ["a", "c", "e"]
    assert sorted(k for k, v in slots.items() if v == "brief") == ["d", "f", "g"]
    assert len(placed) == len(SAMPLE)


def test_the_lead_is_the_highest_importance_and_ties_keep_the_pickers_order() -> None:
    placed = layout.assign_slots(picks(("x", "ai", 8), ("y", "ai", 8), ("z", "ai", 8)))
    assert [p.candidate_id for p in placed] == ["x", "y", "z"]
    assert placed[0].slot == "lead"


def test_small_editions_have_no_empty_slot_gaps() -> None:
    placed = layout.assign_slots(picks(("only", "ai", 9)))
    assert [p.slot for p in placed] == ["lead"]
    assert [
        p.slot for p in layout.assign_slots(picks(("a", "ai", 9), ("b", "ai", 8)))
    ] == ["lead", "secondary"]
    assert layout.assign_slots([]) == []


def test_sections_are_ordered_by_the_readers_interest_then_importance() -> None:
    weights = {"ai": 0.9, "pakistan": 0.7, "climate": 0.2}
    order = layout.order_sections(SAMPLE, weights)
    assert order[:2] == ["ai", "pakistan"]
    assert order.index("world") < order.index(
        "climate"
    )  # world defaults to 0.3 > climate 0.2
    assert set(order) == {"ai", "pakistan", "world", "climate"}


def test_equal_weights_fall_back_to_importance() -> None:
    same = picks(("a", "x", 5), ("b", "y", 9), ("c", "z", 7))
    assert layout.order_sections(same, {"x": 0.5, "y": 0.5, "z": 0.5}) == [
        "y",
        "z",
        "x",
    ]


def test_arrange_puts_the_lead_first_then_sections_in_order() -> None:
    placed = layout.assign_slots(SAMPLE)
    order = layout.order_sections(SAMPLE, {"ai": 0.9, "pakistan": 0.7, "climate": 0.2})
    final = layout.arrange(placed, order)
    assert [p.position for p in final] == list(range(len(SAMPLE)))
    assert final[0].slot == "lead" and final[0].candidate_id == "b"
    sections = [p.section for p in final[1:]]
    first_seen = list(dict.fromkeys(sections))
    assert first_seen == [s for s in order if s in sections]
    pakistan = [p for p in final if p.section == "pakistan"]
    assert [p.slot for p in pakistan] == [
        "secondary",
        "secondary",
    ]  # c(8) and e(9), by importance
    assert [p.importance for p in pakistan] == [9, 8]
