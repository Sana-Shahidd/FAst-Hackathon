"""The newspaper PDF (docs/02_PRD.md F-08): one shared Chromium prints the Paper view template.

The same `edition_print.html` is the "Paper view" page and the PDF, so the web edition and the
PDF always match. Finished PDFs are cached in Supabase Storage (`papers` bucket).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Any

from app import deps
from app.config import PAPER_NAME, settings
from app.services import activity, i18n, reading
from app.services import edition as pipeline

logger = logging.getLogger(__name__)

BUCKET = "papers"
STATIC_DIR = i18n.APP_DIR / "static"
MARGIN = {"top": "12mm", "bottom": "14mm", "left": "12mm", "right": "12mm"}
PAGE_LOAD_TIMEOUT_MS = 30_000
MAX_PARALLEL_RENDERS = 2
MAKING_OF_LINES = 8

_playwright: Any = None
_browser: Any = None
_loop: asyncio.AbstractEventLoop | None = None
_renders: asyncio.Semaphore | None = None
_edition_locks: dict[str, asyncio.Lock] = {}


class PdfUnavailable(RuntimeError):
    """The PDF could not be printed right now; the web edition is unaffected."""


# ------------------------------------------------------------------ browser


def _usable() -> bool:
    """True when the shared browser is alive on the running event loop."""
    return bool(
        _browser is not None
        and _browser.is_connected()
        and _loop is asyncio.get_running_loop()
    )


async def start_browser() -> None:
    """Start the shared Chromium (called once by the app lifespan, or lazily on first use)."""
    global _playwright, _browser, _loop, _renders
    if _usable():
        return
    await stop_browser()
    from playwright.async_api import async_playwright

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(args=["--no-sandbox"])
    _loop = asyncio.get_running_loop()
    _renders = asyncio.Semaphore(MAX_PARALLEL_RENDERS)


async def stop_browser() -> None:
    global _playwright, _browser, _loop, _renders
    browser, runner = _browser, _playwright
    _playwright = _browser = _loop = _renders = None
    for closer in (browser and browser.close, runner and runner.stop):
        if closer:
            try:
                await closer()
            except Exception:
                logger.debug("shared browser shutdown failed", exc_info=True)


async def start_on_startup(application: Any) -> None:
    """Lifespan hook: launch the shared browser and expose it to `/health`; never stops the app."""
    try:
        await start_browser()
        application.state.browser = _browser
    except Exception:
        logger.warning("Chromium did not start; PDFs are unavailable", exc_info=True)


# ------------------------------------------------------------------ context


def footer_template(day: str) -> str:
    """Playwright footer: `Subah · 2026-10-17 · 2 / 4` (digits and ISO date print in any font)."""
    return (
        '<div style="width:100%;padding:0 12mm;font-size:9px;color:#5E6678;'
        'font-family:Arial,sans-serif;display:flex;justify-content:space-between">'
        f"<span>{PAPER_NAME} · {day}</span>"
        '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'
    )


def filename_for(day: str) -> str:
    return f"Subah-{day}.pdf"


def story_link(edition_article_id: str) -> str:
    """Absolute `/r/{id}` link, so headlines stay clickable outside the app (PDF)."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/r/{edition_article_id}"


def _inline_css() -> str:
    return "\n".join(
        (STATIC_DIR / name).read_text(encoding="utf-8")
        for name in ("paper.css", "print.css")
    )


async def build_context(ed: dict, *, pdf: bool) -> dict[str, Any]:
    """Everything `edition_print.html` needs for one ready edition (shared by Paper view and PDF)."""
    user_id, lang = ed["user_id"], ed["lang"]
    profile = await pipeline.get_profile(user_id)
    articles = await reading.edition_articles(ed["id"])
    labels = await reading.interest_labels(user_id)
    favorites = await reading.favorites(user_id)
    steps = await pipeline.steps_for(ed["id"])
    for art in articles:
        art["link"] = story_link(art["id"])
        art["age"] = reading.age_hours((art.get("articles") or {}).get("published_at"))
    lead = next((a for a in articles if a["slot"] == "lead"), None)
    secondary = [a for a in articles if a["slot"] == "secondary"]
    rest = [a for a in articles if a["slot"] == "brief"]
    sections = reading.group_sections(rest, ed.get("section_order") or [])
    titles = reading.section_titles([k for k, _ in sections], lang, labels)
    meta = i18n.languages()[lang]
    day = ed["edition_date"]
    return {
        "lang": lang,
        "dir": i18n.dir(lang),
        "t": lambda key, **vars: i18n.t(key, lang, **vars),
        "paper_name": PAPER_NAME,
        "fonts_url": deps.fonts_url(lang),
        "font_display": meta["font_display"],
        "font_body": meta["font_body"],
        "text_size": profile.text_size if profile else "M",
        "ed": ed,
        "day": day,
        "reader_name": profile.display_name if profile else "",
        "long_date": i18n.full_date(date.fromisoformat(day), lang),
        "printed": reading.printed_time(
            ed.get("ready_at"), profile.timezone if profile else "UTC"
        ),
        "lead": lead,
        "secondary": secondary,
        "sections": [(key, titles[key], items) for key, items in sections],
        "favorite_names": [f["name"] for f in favorites],
        "making_of": [
            s["message"]
            for s in steps
            if s["kind"] in ("decision", "stat", "finished") and s["agent"] != "pdf"
        ][:MAKING_OF_LINES],
        "pdf": pdf,
        "inline_css": _inline_css() if pdf else "",
    }


async def render_html(ed: dict, *, pdf: bool) -> str:
    """The Paper view document; `pdf=True` inlines the CSS so `set_content` needs no server."""
    context = await build_context(ed, pdf=pdf)
    template = deps.templates.env.get_template("edition_print.html")
    return template.render(context)


# ----------------------------------------------------------------- printing


async def print_html(html: str, day: str) -> bytes:
    """Print an HTML document to an A3 PDF with the shared browser."""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    await start_browser()
    assert _browser is not None and _renders is not None
    async with _renders:
        page = await _browser.new_page()
        try:
            try:
                await page.set_content(
                    html, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT_MS
                )
            except PlaywrightTimeout:
                logger.warning("pdf page did not go idle in time; printing anyway")
            await page.emulate_media(media="print")
            await page.evaluate("document.fonts.ready.then(() => true)")
            return await page.pdf(
                format="A3",
                print_background=True,
                margin=MARGIN,
                display_header_footer=True,
                header_template="<span></span>",
                footer_template=footer_template(day),
            )
        finally:
            await page.close()


async def _edition_row(edition_id: str) -> dict:
    client = deps.supabase_admin()
    rows = await asyncio.to_thread(
        lambda: (
            client.table("editions")
            .select("*")
            .eq("id", edition_id)
            .limit(1)
            .execute()
            .data
        )
    )
    if not rows:
        raise LookupError(edition_id)
    return rows[0]


async def _download(path: str) -> bytes | None:
    client = deps.supabase_admin()
    try:
        data = await asyncio.to_thread(
            lambda: client.storage.from_(BUCKET).download(path)
        )
    except Exception:  # noqa: BLE001 - a missing object just means "render again"
        return None
    return data if data[:4] == b"%PDF" else None


async def _upload(path: str, data: bytes, edition_id: str) -> None:
    client = deps.supabase_admin()
    await asyncio.to_thread(
        lambda: client.storage.from_(BUCKET).upload(
            path, data, {"content-type": "application/pdf", "upsert": "true"}
        )
    )
    await asyncio.to_thread(
        lambda: (
            client.table("editions")
            .update({"pdf_path": path})
            .eq("id", edition_id)
            .execute()
        )
    )


async def get_or_render_pdf(edition_id: str) -> bytes:
    """The edition's PDF: the cached copy when there is one, else print it, store it, return it."""
    ed = await _edition_row(edition_id)
    if ed.get("pdf_path") and (cached := await _download(ed["pdf_path"])):
        return cached
    lock = _edition_locks.setdefault(edition_id, asyncio.Lock())
    async with lock:
        try:
            ed = await _edition_row(edition_id)
            if ed.get("pdf_path") and (cached := await _download(ed["pdf_path"])):
                return cached
            return await _render_and_store(ed)
        finally:
            _edition_locks.pop(edition_id, None)


async def _render_and_store(ed: dict) -> bytes:
    started = time.monotonic()
    await activity.log(ed["id"], "pdf", "started", "Printing the PDF")
    try:
        html = await render_html(ed, pdf=True)
        data = await print_html(html, ed["edition_date"])
        path = f"{ed['user_id']}/{ed['edition_date']}-v{ed['version']}.pdf"
        await _upload(path, data, ed["id"])
    except Exception as exc:
        logger.exception("pdf for edition %s failed", ed["id"])
        await activity.log(
            ed["id"], "pdf", "error", f"PDF failed: {type(exc).__name__}"
        )
        raise PdfUnavailable from exc
    ms = int((time.monotonic() - started) * 1000)
    await activity.log(
        ed["id"], "pdf", "finished", f"PDF ready ({len(data) // 1024} KB)", {"ms": ms}
    )
    return data
