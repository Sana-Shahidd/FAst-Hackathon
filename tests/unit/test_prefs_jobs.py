"""Settings validation, mute-word cleaning and the scheduler's "is this paper due?" rule."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from app import jobs
from app.services import prefs

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Crypto", "crypto"),
        ("  Celebrity   Gossip ", "celebrity gossip"),
        ("ab", "ab"),
        ("a", None),
        ("", None),
        ("x" * 41, None),
        ("y" * 40, "y" * 40),
    ],
)
def test_mute_words_are_lower_cased_trimmed_and_length_checked(
    raw: str, expected: str | None
) -> None:
    assert prefs.clean_mute(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("06:00", time(6, 0)),
        ("23:59", time(23, 59)),
        ("00:00", time(0, 0)),
        ("24:00", None),
        ("6:00", None),
        ("06:60", None),
        ("noon", None),
    ],
)
def test_delivery_times_are_hh_mm(raw: str, expected: time | None) -> None:
    assert prefs.parse_delivery_time(raw) == expected


def good(**overrides) -> dict:
    form = {
        "display_name": "  Sana  ",
        "edition_lang": "ur",
        "city": " Lahore ",
        "timezone": "Asia/Karachi",
        "reading_minutes": "20",
        "delivery_time": "05:30",
        "notify": "1",
    }
    return {**form, **overrides}


def test_a_valid_settings_form_becomes_profile_columns() -> None:
    assert prefs.validate_settings(good()) == {
        "display_name": "Sana",
        "edition_lang": "ur",
        "city": "Lahore",
        "timezone": "Asia/Karachi",
        "reading_minutes": 20,
        "delivery_time": "05:30",
        "notify": True,
    }


def test_blank_name_and_city_get_sensible_defaults_and_notify_defaults_off() -> None:
    form = {k: v for k, v in good(display_name="", city="").items() if k != "notify"}
    out = prefs.validate_settings(form)
    assert (out["display_name"], out["city"], out["notify"]) == ("Reader", None, False)


@pytest.mark.parametrize(
    "bad",
    [
        {"edition_lang": "klingon"},
        {"reading_minutes": "7"},
        {"reading_minutes": "lots"},
        {"timezone": "Mars/Olympus"},
        {"delivery_time": "6am"},
    ],
)
def test_invalid_settings_are_rejected_with_a_translatable_message(bad: dict) -> None:
    with pytest.raises(prefs.PrefsError) as caught:
        prefs.validate_settings(good(**bad))
    assert caught.value.key == "auth.error.generic"


NOW = datetime(2026, 10, 17, 1, 30, tzinfo=UTC)  # 06:30 in Karachi, 01:30 in London


@pytest.mark.parametrize(
    ("zone", "delivery", "has_edition", "due"),
    [
        ("Asia/Karachi", time(6, 0), False, True),  # 06:30 local, delivery at 06:00
        ("Asia/Karachi", time(7, 0), False, False),  # not yet
        ("Asia/Karachi", time(6, 0), True, False),  # already printed
        ("UTC", time(1, 30), False, True),  # exactly on time
        ("Europe/London", time(6, 0), False, False),  # 02:30 local (BST), still night
        ("Not/AZone", time(1, 0), False, True),  # unknown zone counts as UTC
    ],
)
def test_a_paper_is_due_once_the_readers_clock_passes_their_delivery_time(
    zone: str, delivery: time, has_edition: bool, due: bool
) -> None:
    assert jobs.is_due(NOW, zone, delivery, has_edition) is due


def test_delivery_times_from_the_database_may_carry_seconds() -> None:
    assert jobs._delivery("06:00:00") == time(6, 0)
    assert jobs._delivery(None) == time(6, 0)
    assert jobs._delivery("07:45") == time(7, 45)
