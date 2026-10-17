"""UI strings, text direction and localized dates (docs/07_DESIGN.md §6).

String tables live in `app/i18n/<lang>.json` (121 keys, identical in all 8 files) and
language metadata in `app/data/languages.json`; neither is generated at runtime.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from babel.dates import format_date

APP_DIR = Path(__file__).resolve().parent.parent
I18N_DIR = APP_DIR / "i18n"
DATA_DIR = APP_DIR / "data"
DEFAULT_LANG = "en"


@lru_cache(maxsize=1)
def languages() -> dict[str, dict[str, Any]]:
    """`app/data/languages.json`: dir, babel locale, fonts, Google News edition."""
    return json.loads((DATA_DIR / "languages.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_tables() -> dict[str, dict[str, str]]:
    """Every `app/i18n/<lang>.json` string table, keyed by language code."""
    return {
        lang: json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in languages()
    }


def t(key: str, lang: str = DEFAULT_LANG, **vars: Any) -> str:
    """Localized UI string, falling back to English and then to the key itself."""
    tables = load_tables()
    table = tables.get(lang, tables[DEFAULT_LANG])
    text = table.get(key) or tables[DEFAULT_LANG].get(key, key)
    return text.format(**vars) if vars else text


# Name fixed by docs/03_TECH.md §3; shadows the builtin inside this module only.
def dir(lang: str) -> str:
    """`"rtl"` for Urdu and Arabic, `"ltr"` for every other supported language."""
    return languages().get(lang, {}).get("dir", "ltr")


def full_date(value: date, lang: str = DEFAULT_LANG) -> str:
    """Full localized date, e.g. "Saturday, 17 October 2026"."""
    locale = languages().get(lang, {}).get("babel", DEFAULT_LANG)
    return format_date(value, format="full", locale=locale)
