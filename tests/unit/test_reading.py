"""Read marks from signals, story age, printed time, source badges and section grouping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services import reading

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 17, 6, 0, tzinfo=UTC)


def test_only_open_and_click_signals_of_this_edition_count_as_read() -> None:
    rows = [
        {"kind": "open", "edition_article_id": "a"},
        {"kind": "click", "edition_article_id": "b"},
        {"kind": "more_like", "edition_article_id": "c"},
        {"kind": "dwell", "edition_article_id": "d"},
        {"kind": "open", "edition_article_id": "elsewhere"},
        {"kind": "open", "edition_article_id": None},
    ]
    valid = {"a", "b", "c", "d"}
    assert reading.read_ids_from_signals(rows, valid) == {"a", "b"}


def test_a_story_opened_twice_is_read_once() -> None:
    rows = [{"kind": "open", "edition_article_id": "a"}] * 2 + [
        {"kind": "click", "edition_article_id": "a"}
    ]
    assert reading.read_ids_from_signals(rows, {"a"}) == {"a"}


def test_no_signals_means_nothing_is_read() -> None:
    assert reading.read_ids_from_signals([], {"a"}) == set()


def test_the_bookmark_toggles_between_saved_and_unsaved() -> None:
    assert reading.toggled(False) is True
    assert reading.toggled(True) is False


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        (NOW - timedelta(minutes=10), 1),  # never "0 hours ago"
        (NOW - timedelta(hours=3, minutes=20), 3),
        (NOW - timedelta(hours=30), 30),
        (None, -1),
        ("", -1),
    ],
)
def test_age_in_whole_hours_with_a_floor_of_one(published, expected) -> None:
    assert reading.age_hours(published, NOW) == expected


def test_age_accepts_the_iso_strings_supabase_returns() -> None:
    assert reading.age_hours("2026-10-17T03:00:00+00:00", NOW) == 3
    assert reading.age_hours("2026-10-17T03:00:00Z", NOW) == 3


def test_printed_time_is_shown_in_the_readers_timezone() -> None:
    stamp = "2026-10-17T01:02:00+00:00"
    assert reading.printed_time(stamp, "Asia/Karachi") == "06:02"
    assert reading.printed_time(stamp, "UTC") == "01:02"
    assert reading.printed_time(stamp, "Not/AZone") == "01:02"
    assert reading.printed_time(None, "UTC") == ""


def test_source_badges_use_the_catalog_and_fall_back_to_initials() -> None:
    circles = reading.source_circles(
        [
            {"catalog_key": "bbc", "name": "BBC News"},
            {"catalog_key": None, "name": "My Favourite Blog"},
            {"catalog_key": None, "name": "Dawn"},
        ]
    )
    assert circles[0]["initials"] == "BBC" and circles[0]["color"].startswith("#")
    assert circles[1]["initials"] == "MF"
    assert circles[2]["initials"] == "DA"
    assert all(c["color"] for c in circles)


def test_initials_of_odd_names() -> None:
    assert reading.initials("Al Jazeera") == "AJ"
    assert reading.initials("") == "?"
    assert reading.initials("X") == "X"


def art(id_: str, section: str, slot: str, position: int) -> dict:
    return {"id": id_, "section": section, "slot": slot, "position": position}


def test_sections_follow_the_edition_order_and_exclude_the_lead() -> None:
    articles = [
        art("lead", "ai", "lead", 0),
        art("p2", "pakistan", "brief", 3),
        art("a1", "ai", "secondary", 1),
        art("p1", "pakistan", "secondary", 2),
        art("w1", "world", "brief", 4),
    ]
    groups = reading.group_sections(articles, ["pakistan", "ai", "world"])
    assert [key for key, _ in groups] == ["pakistan", "ai", "world"]
    assert [a["id"] for a in groups[0][1]] == ["p1", "p2"]  # by position
    assert [a["id"] for a in groups[1][1]] == ["a1"]  # the lead is not repeated


def test_a_section_missing_from_the_order_is_still_shown_last() -> None:
    groups = reading.group_sections(
        [art("x", "climate", "brief", 1), art("y", "ai", "brief", 2)], ["ai"]
    )
    assert [key for key, _ in groups] == ["ai", "climate"]


def ed(day: str, version: int, status: str = "ready") -> dict:
    return {
        "edition_date": day,
        "version": version,
        "status": status,
        "id": f"{day}-v{version}",
    }


def test_archive_lists_dates_newest_first_with_older_versions_collapsed() -> None:
    rows = [
        ed("2026-10-15", 1),
        ed("2026-10-17", 1, "superseded"),
        ed("2026-10-17", 2),
        ed("2026-10-16", 1),
    ]
    entries = reading.group_editions(rows)
    assert [e["day"] for e in entries] == ["2026-10-17", "2026-10-16", "2026-10-15"]
    assert entries[0]["latest"]["version"] == 2
    assert [o["version"] for o in entries[0]["older"]] == [1]
    assert entries[1]["older"] == [] and entries[2]["older"] == []


def test_an_empty_archive_has_no_entries() -> None:
    assert reading.group_editions([]) == []


def save(day: str, saved_at: str, name: str) -> dict:
    return {
        "created_at": saved_at,
        "edition_articles": {"id": name, "editions": {"edition_date": day}},
    }


def test_saved_stories_are_grouped_by_edition_date_newest_first() -> None:
    rows = [
        save("2026-10-15", "2026-10-17T08:00:00+00:00", "old-day-late-save"),
        save("2026-10-17", "2026-10-17T07:00:00+00:00", "today-first"),
        save("2026-10-17", "2026-10-17T09:00:00+00:00", "today-second"),
    ]
    groups = reading.group_saved(rows)
    assert [day for day, _ in groups] == ["2026-10-17", "2026-10-15"]
    names = [r["edition_articles"]["id"] for r in groups[0][1]]
    assert names == ["today-second", "today-first"]  # newest save first inside a date


def test_nothing_saved_means_no_groups() -> None:
    assert reading.group_saved([]) == []
