"""Signal weights, clamping, the dwell threshold, low-weight timing and the profile sparkline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import (
    WEIGHT_CLICK,
    WEIGHT_DWELL,
    WEIGHT_IGNORED,
    WEIGHT_LESS,
    WEIGHT_MORE,
    WEIGHT_PUZZLE,
    WEIGHT_SAVE,
)
from app.services import learning

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 17, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("click", WEIGHT_CLICK),
        ("more_like", WEIGHT_MORE),
        ("less_like", WEIGHT_LESS),
        ("save", WEIGHT_SAVE),
        ("puzzle_correct", WEIGHT_PUZZLE),
        ("impression_no_click", WEIGHT_IGNORED),
    ],
)
def test_every_signal_kind_changes_the_weight_by_its_constant(
    kind: str, expected: float
) -> None:
    assert learning.delta_for(kind) == expected


def test_the_prd_numbers_are_the_constants() -> None:
    assert (WEIGHT_CLICK, WEIGHT_MORE, WEIGHT_LESS) == (0.08, 0.15, -0.15)
    assert (WEIGHT_SAVE, WEIGHT_PUZZLE, WEIGHT_DWELL, WEIGHT_IGNORED) == (
        0.10,
        0.03,
        0.04,
        -0.02,
    )


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(5, 0.0), (19.9, 0.0), (20, WEIGHT_DWELL), (300, WEIGHT_DWELL)],
)
def test_a_dwell_only_counts_after_twenty_seconds(
    seconds: float, expected: float
) -> None:
    assert learning.delta_for("dwell", seconds) == expected


@pytest.mark.parametrize("kind", ["open", "pdf", "skip_source", "taste_up", "nonsense"])
def test_other_signals_do_not_move_weights(kind: str) -> None:
    assert learning.delta_for(kind) == 0.0


def test_a_missing_dwell_value_counts_for_nothing() -> None:
    assert learning.delta_for("dwell", None) == 0.0


@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        (1.4, 1.0),
        (1.0, 1.0),
        (0.5, 0.5),
        (0.05, 0.05),
        (0.01, 0.05),
        (-3, 0.05),
        (0.6000001, 0.6),
    ],
)
def test_weights_clamp_to_the_allowed_range_and_round(
    weight: float, expected: float
) -> None:
    assert learning.clamp(weight) == expected


def test_repeated_likes_stop_at_the_ceiling_and_dislikes_at_the_floor() -> None:
    up = down = 0.9
    for _ in range(5):
        up = learning.clamp(up + learning.delta_for("more_like"))
        down = learning.clamp(down + learning.delta_for("less_like") * 3)
    assert up == 1.0 and down == 0.05


def test_low_since_starts_below_a_tenth_and_resets_on_recovery() -> None:
    assert learning.low_since_after(0.08, None, NOW) == NOW.isoformat()
    earlier = (NOW - timedelta(days=3)).isoformat()
    assert (
        learning.low_since_after(0.08, earlier, NOW) == earlier
    )  # keeps the first moment
    assert learning.low_since_after(0.1, earlier, NOW) is None
    assert learning.low_since_after(0.6, None, NOW) is None


def test_an_interest_low_for_seven_days_is_long_low() -> None:
    assert learning.long_low(None, NOW) is False
    assert (
        learning.long_low((NOW - timedelta(days=6, hours=23)).isoformat(), NOW) is False
    )
    assert learning.long_low((NOW - timedelta(days=7)).isoformat(), NOW) is True


def test_history_series_starts_at_the_old_weight_then_follows_every_change() -> None:
    rows = [
        {
            "old_weight": 0.7,
            "new_weight": 0.85,
            "created_at": "2026-10-16T08:00:00+00:00",
        },
        {
            "old_weight": 0.85,
            "new_weight": 0.77,
            "created_at": "2026-10-17T08:00:00+00:00",
        },
    ]
    assert learning.history_series(0.77, rows) == [0.7, 0.85, 0.77]
    assert learning.history_series(0.77, list(reversed(rows))) == [
        0.7,
        0.85,
        0.77,
    ]  # sorted by time
    assert learning.history_series(0.5, []) == [0.5]


def test_sparkline_maps_weights_into_the_box_and_flat_for_one_value() -> None:
    points = learning.sparkline_points([0.0, 1.0], width=100, height=22).split()
    assert points[0].startswith("0.0,") and points[1].startswith("100.0,")
    low_y, high_y = (float(p.split(",")[1]) for p in points)
    assert high_y < low_y  # a higher weight is drawn higher up
    flat = learning.sparkline_points([0.5]).split()
    assert len(flat) == 2 and flat[0].split(",")[1] == flat[1].split(",")[1]
    assert learning.sparkline_points([]) == ""
