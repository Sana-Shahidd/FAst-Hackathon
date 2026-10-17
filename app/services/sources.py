"""Source catalog and custom feed validation (F-23)."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from functools import cache
from urllib.parse import urlparse

import feedparser
import httpx

from app.config import FEED_TIMEOUT_S
from app.services import i18n
from app.services.feeds import USER_AGENT


@cache
def catalog() -> dict[str, list[dict]]:
    """`app/data/sources.json`: outlets per language."""
    return json.loads((i18n.DATA_DIR / "sources.json").read_text(encoding="utf-8"))


def catalog_for(lang: str) -> list[dict]:
    """Outlets offered to a reader of `lang`: native outlets first, then English ones."""
    native = catalog().get(lang, [])
    english = [] if lang == "en" else catalog().get("en", [])
    return [*native, *english]


def entry_for(key: str) -> dict | None:
    """Catalog entry by key, searching every language."""
    for outlets in catalog().values():
        for outlet in outlets:
            if outlet["key"] == key:
                return outlet
    return None


async def _is_public_host(host: str) -> bool:
    """True only if every address of `host` is a public internet address (blocks SSRF)."""
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        except OSError:
            return False
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    return bool(addresses) and all(address.is_global for address in addresses)


async def validate_custom_feed(url: str) -> tuple[bool, str | None]:
    """(ok, feed title): http(s) URL on a public host that parses as a feed.

    Rejected: other schemes, private/loopback hosts, and anything `feedparser` flags as
    malformed (`bozo`) with no entries.
    """
    parts = urlparse(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False, None
    if not await _is_public_host(parts.hostname):
        return False, None
    try:
        async with httpx.AsyncClient(
            timeout=FEED_TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url.strip())
        response.raise_for_status()
    except httpx.HTTPError:
        return False, None
    final_host = urlparse(str(response.url)).hostname
    if not final_host or not await _is_public_host(final_host):
        return False, None
    parsed = feedparser.parse(response.text)
    if parsed.bozo and not parsed.entries:
        return False, None
    title = parsed.feed.get("title") if parsed.get("feed") else None
    return True, (title or "").strip() or None
