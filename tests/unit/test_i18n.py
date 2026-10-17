"""Unit tests for `app/services/i18n.py` (docs/09_SETUP_TEST_DEMO.md §2)."""

from __future__ import annotations

from datetime import date

import pytest

from app.services import i18n

pytestmark = pytest.mark.unit

SUPPORTED = {"en", "ur", "ar", "hi", "bn", "es", "fr", "zh"}
RTL = {"ur", "ar"}


def test_all_eight_tables_share_identical_keys() -> None:
    tables = i18n.load_tables()
    assert set(tables) == SUPPORTED
    en_keys = set(tables["en"])
    assert len(en_keys) >= 121
    for lang, table in tables.items():
        assert set(table) == en_keys, f"{lang}.json keys differ from en.json"
        assert all(value.strip() for value in table.values()), (
            f"{lang}.json has a blank value"
        )


def test_t_formats_placeholders_in_every_language() -> None:
    assert i18n.t("ob.step", "en", n=3) == "Step 3 of 5"
    for lang in SUPPORTED:
        assert "3" in i18n.t("ob.step", lang, n=3)
        assert "{n}" not in i18n.t("ob.step", lang, n=3)


def test_t_returns_the_language_string_not_english() -> None:
    assert i18n.t("nav.today", "ur") != i18n.t("nav.today", "en")
    assert i18n.t("nav.today", "ur") == i18n.load_tables()["ur"]["nav.today"]


def test_t_falls_back_to_english_then_to_the_key() -> None:
    assert i18n.t("nav.today", "xx") == i18n.t("nav.today", "en")
    assert i18n.t("no.such.key", "en") == "no.such.key"


def test_dir_is_rtl_for_urdu_and_arabic_only() -> None:
    for lang in SUPPORTED:
        assert i18n.dir(lang) == ("rtl" if lang in RTL else "ltr")
    assert i18n.dir("xx") == "ltr"


def test_full_date_is_localized_per_locale() -> None:
    day = date(2026, 10, 17)
    english = i18n.full_date(day, "en")
    assert "Saturday" in english
    assert "October" in english
    assert "2026" in english
    rendered = {lang: i18n.full_date(day, lang) for lang in SUPPORTED}
    assert len(set(rendered.values())) == len(SUPPORTED)
    for lang in ("ur", "ar", "hi", "bn", "zh"):
        assert not rendered[lang].isascii(), f"{lang} date is not in its own script"
