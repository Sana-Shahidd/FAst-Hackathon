"""Source catalog (native first, then English) and custom feed validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx

from app.config import SUPPORTED_LANGS
from app.services import sources

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def public_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip DNS: treat every named host as public (IP literals are still checked)."""

    async def fake(host: str) -> bool:
        return host not in ("localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254")

    monkeypatch.setattr(sources, "_is_public_host", fake)


def test_catalog_has_the_documented_shape_for_every_language() -> None:
    assert set(sources.catalog()) == set(SUPPORTED_LANGS)
    for lang, outlets in sources.catalog().items():
        assert outlets, lang
        for outlet in outlets:
            assert {"key", "name", "domain", "feed_url", "initials", "color"} <= set(
                outlet
            )
            assert outlet["feed_url"].startswith("https://")


def test_catalog_lists_native_outlets_first_then_english() -> None:
    urdu = [o["key"] for o in sources.catalog_for("ur")]
    assert urdu[0] == "bbc_urdu"
    assert urdu[1:] == [o["key"] for o in sources.catalog()["en"]]
    french = [o["key"] for o in sources.catalog_for("fr")]
    assert french[:2] == ["france24_fr", "lemonde"]
    assert french[2:] == [o["key"] for o in sources.catalog()["en"]]


def test_english_catalog_is_not_duplicated() -> None:
    keys = [o["key"] for o in sources.catalog_for("en")]
    assert keys == [o["key"] for o in sources.catalog()["en"]]
    assert len(keys) == len(set(keys))


def test_entry_for_finds_outlets_in_any_language() -> None:
    assert sources.entry_for("bbc_hindi")["name"].startswith("BBC")
    assert sources.entry_for("dawn")["domain"] == "dawn.com"
    assert sources.entry_for("nope") is None


@pytest.mark.parametrize(
    "url",
    [
        "ftp://feeds.example.com/rss",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "feeds.example.com",
        "",
    ],
)
async def test_non_http_urls_are_rejected(url: str) -> None:
    assert await sources.validate_custom_feed(url) == (False, None)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/feed",
        "http://127.0.0.1/rss",
        "http://10.0.0.5/rss",
        "http://169.254.169.254/latest",
    ],
)
async def test_private_and_loopback_hosts_are_rejected(url: str) -> None:
    assert await sources.validate_custom_feed(url) == (False, None)


@respx.mock
async def test_a_good_feed_is_accepted_with_its_title(public_hosts: None) -> None:
    respx.get("https://blog.example.com/feed.xml").respond(
        200, content=(FIXTURES / "custom_good.xml").read_bytes()
    )
    assert await sources.validate_custom_feed("https://blog.example.com/feed.xml") == (
        True,
        "My Favourite Blog",
    )


@respx.mock
async def test_an_html_page_is_rejected(public_hosts: None) -> None:
    respx.get("https://site.example.com/").respond(
        200, content=(FIXTURES / "not_a_feed.html").read_bytes()
    )
    assert await sources.validate_custom_feed("https://site.example.com/") == (
        False,
        None,
    )


@respx.mock
async def test_http_errors_are_rejected(public_hosts: None) -> None:
    respx.get("https://gone.example.com/rss").respond(404)
    assert await sources.validate_custom_feed("https://gone.example.com/rss") == (
        False,
        None,
    )


@respx.mock
async def test_redirect_to_a_private_host_is_rejected(public_hosts: None) -> None:
    respx.get("https://short.example.com/rss").respond(
        302, headers={"location": "http://127.0.0.1/rss"}
    )
    respx.get("http://127.0.0.1/rss").respond(
        200, content=(FIXTURES / "custom_good.xml").read_bytes()
    )
    assert await sources.validate_custom_feed("https://short.example.com/rss") == (
        False,
        None,
    )
