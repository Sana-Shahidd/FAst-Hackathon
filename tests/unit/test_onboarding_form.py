"""`parse_onboarding`: every rule of the onboarding form table in docs/05_ROUTES.md."""

from __future__ import annotations

import json

import pytest
from starlette.datastructures import FormData

from app.services import onboarding
from app.services.onboarding import OnboardingError, final_weights, parse_onboarding

pytestmark = pytest.mark.unit

BASE = [
    ("edition_lang", "en"),
    ("topics", "ai"),
    ("topics", "pakistan"),
    ("topics", "startups"),
]


def form(*extra: tuple[str, str]) -> FormData:
    return FormData([*BASE, *extra])


def test_minimal_valid_form_gets_sensible_defaults() -> None:
    data = parse_onboarding(form())
    assert data.edition_lang == "en" and data.source_langs == []
    assert [(t.key, t.weight) for t in data.topics] == [
        ("ai", 0.7),
        ("pakistan", 0.7),
        ("startups", 0.7),
    ]
    assert (data.timezone, data.reading_minutes, data.notify) == ("UTC", 10, False)
    assert data.city is None and data.display_name is None


def test_fewer_than_three_known_topics_is_an_error() -> None:
    with pytest.raises(OnboardingError) as err:
        parse_onboarding(
            FormData([("topics", "ai"), ("topics", "pakistan"), ("topics", "nonsense")])
        )
    assert err.value.key == "ob.topics.min"
    with pytest.raises(OnboardingError):
        parse_onboarding(FormData([]))


def test_levels_map_to_weights_and_bad_levels_default_to_a_lot() -> None:
    data = parse_onboarding(
        form(
            ("topic_level_ai", "1"),
            ("topic_level_pakistan", "3"),
            ("topic_level_startups", "9"),
        )
    )
    assert {t.key: t.weight for t in data.topics} == {
        "ai": 0.4,
        "pakistan": 1.0,
        "startups": 0.7,
    }
    assert parse_onboarding(form(("topic_level_ai", "x"))).topics[0].weight == 0.7


def test_unknown_language_falls_back_to_english_and_source_langs_are_limited() -> None:
    data = parse_onboarding(
        FormData(
            [
                *BASE[1:],
                ("edition_lang", "xx"),
                ("source_langs", "ur"),
                ("source_langs", "ur"),
                ("source_langs", "klingon"),
            ]
        )
    )
    assert data.edition_lang == "en" and data.source_langs == ["ur"]
    many = parse_onboarding(
        FormData(
            [*BASE, *[("source_langs", c) for c in ("en", "ur", "ar", "hi", "bn")]]
        )
    )
    assert "en" not in many.source_langs  # the edition language is not an "extra"
    assert many.source_langs == ["ur", "ar", "hi"]  # at most 3


def test_taste_votes_move_the_topic_weight_by_015_and_clamp() -> None:
    votes = [
        {"topic_key": "ai", "vote": "up"},
        {"topic_key": "ai", "vote": "up"},
        {"topic_key": "pakistan", "vote": "down"},
        {"topic_key": "space", "vote": "up"},
        {"topic_key": "ai", "vote": "meh"},
    ]
    data = parse_onboarding(
        form(
            ("taste", json.dumps(votes)),
            ("topic_level_ai", "3"),
            ("topic_level_pakistan", "1"),
        )
    )
    assert data.taste == {
        "ai": 0.3,
        "pakistan": -0.15,
    }  # "space" was not picked; "meh" ignored
    weights = final_weights(data)
    assert weights["ai"] == (1.0, 1.0)  # clamped at WEIGHT_MAX
    assert weights["pakistan"] == (0.4, 0.25)
    assert weights["startups"] == (0.7, 0.7)


def test_weight_never_drops_below_the_minimum() -> None:
    votes = [{"topic_key": "ai", "vote": "down"}] * 5
    data = parse_onboarding(form(("taste", json.dumps(votes)), ("topic_level_ai", "1")))
    assert final_weights(data)["ai"][1] == 0.05


def test_custom_interests_are_cleaned_and_capped() -> None:
    items = [{"label": f"topic {n}", "query": f'"q{n}"'} for n in range(8)]
    items += [
        {"label": "topic 0", "query": "dup"},
        {"label": "", "query": "x"},
        "junk",
        {"label": "no query"},
    ]
    data = parse_onboarding(form(("custom_interests", json.dumps(items))))
    assert [i.label for i in data.custom_interests] == [f"topic {n}" for n in range(5)]


def test_favorites_must_be_in_the_catalog_for_the_language_or_english() -> None:
    keys = ["bbc", "dawn", "bbc_urdu", "nope"]
    en = parse_onboarding(form(("favorite_sources", json.dumps(keys))))
    assert en.favorite_sources == [
        "bbc",
        "dawn",
    ]  # bbc_urdu is not offered to English readers
    ur = parse_onboarding(
        FormData(
            [*BASE, ("edition_lang", "ur"), ("favorite_sources", json.dumps(keys))]
        )
    )
    assert ur.favorite_sources == [
        "bbc",
        "dawn",
        "bbc_urdu",
    ]  # native + English outlets
    many = [o["key"] for o in onboarding.sources.catalog_for("en")] * 2
    assert (
        len(
            parse_onboarding(
                form(("favorite_sources", json.dumps(many)))
            ).favorite_sources
        )
        <= 10
    )


def test_custom_feeds_keep_http_urls_only_and_at_most_five() -> None:
    urls = [f"https://site{n}.example.com/rss" for n in range(7)] + [
        "ftp://x.example.com",
        "javascript:1",
        5,
    ]
    data = parse_onboarding(form(("custom_feeds", json.dumps(urls))))
    assert data.custom_feeds == urls[:5]


def test_muted_keywords_are_trimmed_lowercased_deduped_and_length_checked() -> None:
    words = [" Crypto ", "crypto", "a", "x" * 41, "Celebrity gossip", 77]
    data = parse_onboarding(form(("muted_keywords", json.dumps(words))))
    assert data.muted_keywords == ["crypto", "celebrity gossip", "77"]
    many = [f"word{n:02d}" for n in range(40)]
    assert (
        len(parse_onboarding(form(("muted_keywords", json.dumps(many)))).muted_keywords)
        == 30
    )


def test_morning_settings_are_validated() -> None:
    data = parse_onboarding(
        form(
            ("city", "  Lahore  "),
            ("timezone", "Asia/Karachi"),
            ("reading_minutes", "20"),
            ("notify", "1"),
            ("display_name", "  " + "n" * 60),
        )
    )
    assert (data.city, data.timezone, data.reading_minutes, data.notify) == (
        "Lahore",
        "Asia/Karachi",
        20,
        True,
    )
    assert data.display_name == "n" * 40
    bad = parse_onboarding(form(("timezone", "Mars/Olympus"), ("reading_minutes", "7")))
    assert (bad.timezone, bad.reading_minutes) == ("UTC", 10)
    assert parse_onboarding(form(("reading_minutes", "abc"))).reading_minutes == 10


def test_malformed_json_fields_are_ignored_not_fatal() -> None:
    data = parse_onboarding(
        form(
            ("taste", "{not json"),
            ("custom_interests", '"a string"'),
            ("favorite_sources", "null"),
            ("muted_keywords", "7"),
        )
    )
    assert (
        data.taste,
        data.custom_interests,
        data.favorite_sources,
        data.muted_keywords,
    ) == ({}, [], [], [])
