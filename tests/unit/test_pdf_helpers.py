"""PDF helpers that need no browser: footer, file name, absolute links, print rules."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import pdf

pytestmark = pytest.mark.unit


def test_footer_shows_the_paper_the_date_and_page_x_of_y() -> None:
    footer = pdf.footer_template("2026-10-17")
    assert "Subah · 2026-10-17" in footer
    assert 'class="pageNumber"' in footer and 'class="totalPages"' in footer
    assert "font-size:9px" in footer  # Chromium prints footers at size 0 unless told


def test_the_download_is_named_after_the_date() -> None:
    assert pdf.filename_for("2026-10-17") == "Subah-2026-10-17.pdf"


@pytest.mark.parametrize("base", ["https://subah.example", "https://subah.example/"])
def test_story_links_are_absolute_and_go_through_the_redirect(
    monkeypatch: pytest.MonkeyPatch, base: str
) -> None:
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", base)
    assert pdf.story_link("abc-123") == "https://subah.example/r/abc-123"


def test_inlined_css_carries_the_broadsheet_print_rules() -> None:
    css = pdf._inline_css()
    assert "@page" in css and "size: A3" in css
    assert "column-count: 5" in css  # five newspaper columns on A3
    assert "break-before: page" in css  # "How this paper was made" gets its own page
    assert "--navy-950" in css  # paper.css comes first, then print.css


def test_margins_match_the_prd() -> None:
    assert pdf.MARGIN == {
        "top": "12mm",
        "bottom": "14mm",
        "left": "12mm",
        "right": "12mm",
    }
