"""Brand assets: the logo, its cropped mark, the header video and the templates that use them."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

APP = Path(__file__).resolve().parent.parent.parent / "app"
STATIC = APP / "static"
TEMPLATES = APP / "templates"


@pytest.mark.parametrize(
    ("path", "min_bytes"),
    [
        ("logo.webp", 10_000),
        ("logo-mark.png", 5_000),
        ("video/subah_header_background.mp4", 100_000),
    ],
)
def test_brand_assets_exist_and_are_not_empty(path: str, min_bytes: int) -> None:
    assert (STATIC / path).stat().st_size >= min_bytes


def test_the_video_is_a_real_mp4() -> None:
    head = (STATIC / "video/subah_header_background.mp4").read_bytes()[:12]
    assert head[4:8] == b"ftyp"  # ISO base media file


def test_the_logo_is_a_webp_and_the_mark_a_png() -> None:
    assert (STATIC / "logo.webp").read_bytes()[:4] == b"RIFF"
    assert (STATIC / "logo-mark.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_header_video_is_muted_looping_inline_and_never_blocks_clicks() -> None:
    html = (TEMPLATES / "edition.html").read_text(encoding="utf-8")
    video = html[html.index("<video") : html.index("</video>")]
    for attribute in ("autoplay", "muted", "loop", "playsinline", 'preload="metadata"'):
        assert attribute in video
    assert "/static/video/subah_header_background.mp4" in video
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "object-fit: cover" in css and "pointer-events: none" in css
    assert "prefers-reduced-motion: reduce" in css and ".hero-video" in css


def test_pages_use_the_logo_and_the_favicon_is_the_mark() -> None:
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "/static/logo-mark.png" in base
    assert "/static/logo.webp" in (TEMPLATES / "landing.html").read_text(
        encoding="utf-8"
    )
    for name in ("landing", "_auth_form", "onboarding", "generating", "error"):
        assert "/static/logo-mark.png" in (TEMPLATES / f"{name}.html").read_text(
            encoding="utf-8"
        )
