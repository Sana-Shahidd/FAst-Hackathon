"""Paper view and the A3 PDF through the real routes, real Chromium and real Storage (T-08, F-08)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import i18n, pdf

pytestmark = pytest.mark.integration

REAL_START_ON_STARTUP = pdf.start_on_startup  # the autouse fixture replaces it per test


def edition_row(admin, edition_id: str) -> dict:
    return admin.table("editions").select("*").eq("id", edition_id).execute().data[0]


def count_prints(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Wrap `pdf.print_html` so a test can see how many times Chromium really printed."""
    calls: list[str] = []
    real = pdf.print_html

    async def spy(html: str, day: str) -> bytes:
        calls.append(day)
        return await real(html, day)

    monkeypatch.setattr(pdf, "print_html", spy)
    return calls


def test_the_pdf_is_a_real_multi_page_a3_document_and_is_cached(
    client: TestClient, edition, admin, onboarded_user, monkeypatch
) -> None:
    prints = count_prints(monkeypatch)
    url = f"/paper/{edition['day']}/pdf"
    first = client.get(url)
    assert first.status_code == 200
    assert first.headers["content-type"] == "application/pdf"
    assert (
        first.headers["content-disposition"]
        == f'attachment; filename="Subah-{edition["day"]}.pdf"'
    )
    data = first.content
    assert data.startswith(b"%PDF") and len(data) > 20_000
    assert re.search(
        rb"/MediaBox \[0 0 84\d\.\d+ 119\d\.\d+\]", data
    )  # A3 (842 x 1191 pt)
    assert (
        len(re.findall(rb"/Type\s*/Page[^s]", data)) >= 2
    )  # front page + making-of page

    path = f"{onboarded_user.id}/{edition['day']}-v1.pdf"
    assert edition_row(admin, edition["id"])["pdf_path"] == path
    stored = admin.storage.from_("papers").download(path)
    assert stored == data  # what we streamed is what is stored

    second = client.get(url)
    assert second.status_code == 200 and second.content == data
    assert len(prints) == 1  # the second download came from Storage, not Chromium


def test_the_pdf_is_logged_and_recorded_as_a_signal(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    client.get(f"/paper/{edition['day']}/pdf")
    signals = (
        admin.table("signals")
        .select("kind,edition_article_id")
        .eq("user_id", onboarded_user.id)
        .eq("kind", "pdf")
        .execute()
        .data
    )
    assert [s["edition_article_id"] for s in signals] == [None]
    steps = (
        admin.table("agent_activity")
        .select("agent,kind")
        .eq("edition_id", edition["id"])
        .eq("agent", "pdf")
        .execute()
        .data
    )
    assert {s["kind"] for s in steps} == {"started", "finished"}


def test_paper_view_is_the_pdf_markup_with_absolute_clickable_headlines(
    client: TestClient, edition, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://subah.example")
    page = client.get(f"/paper/{edition['day']}/print")
    assert page.status_code == 200
    html = page.text
    assert 'class="paper"' in html and "/static/paper.css" in html
    assert 'lang="en"' in html and 'dir="ltr"' in html
    assert "Test lead headline" in html and "Fact 1 from today" in html
    assert i18n.t("paper.three_things", "en") in html
    for art in edition["articles"]:
        assert f'href="https://subah.example/r/{art["id"]}"' in html
    assert f"/paper/{edition['day']}/pdf" in html  # the "Download PDF" button


def test_the_pdf_document_inlines_its_css_so_chromium_needs_no_server(
    edition, admin
) -> None:
    import asyncio

    ed = edition_row(admin, edition["id"])
    html = asyncio.run(pdf.render_html(ed, pdf=True))
    assert "<style>" in html and "column-count: 5" in html
    assert (
        "/static/paper.css" not in html and "paper-bar" not in html.split("</head>")[1]
    )
    assert (
        "Test lead headline" in html
    )  # the front page uses the Editor's lead headline
    for art in edition["articles"]:
        if art["slot"] != "lead":
            assert art["headline"] in html


def test_an_urdu_edition_is_right_to_left_and_embeds_the_nastaliq_font(
    client: TestClient, edition, admin
) -> None:
    admin.table("editions").update({"lang": "ur"}).eq("id", edition["id"]).execute()
    html = client.get(f"/paper/{edition['day']}/print").text
    assert 'lang="ur"' in html and 'dir="rtl"' in html
    assert "Noto Nastaliq Urdu" in html
    assert i18n.t("paper.three_things", "ur") in html
    response = client.get(f"/paper/{edition['day']}/pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    fonts = re.findall(rb"/FontName /[A-Z]+\+([A-Za-z0-9_-]+)", response.content)
    assert any(b"Nastaliq" in f for f in fonts), b" ".join(
        sorted(set(fonts))
    ).decode()  # the Urdu font made it into the file


def test_strangers_signed_out_visitors_and_bad_dates_get_nothing(
    client: TestClient, edition, admin, make_user, post_form, onboarded_user
) -> None:
    for path in ("print", "pdf"):
        assert client.get(f"/paper/2001-01-01/{path}").status_code == 404
        assert client.get(f"/paper/not-a-date/{path}").status_code == 404
        anonymous = TestClient(app).get(
            f"/paper/{edition['day']}/{path}", follow_redirects=False
        )
        assert (anonymous.status_code, anonymous.headers["location"]) == (303, "/login")
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    for path in ("print", "pdf"):  # not onboarded: sent to onboarding, nothing rendered
        response = browser.get(
            f"/paper/{edition['day']}/{path}", follow_redirects=False
        )
        assert (response.status_code, response.headers["location"]) == (
            303,
            "/onboarding",
        )
    assert edition_row(admin, edition["id"])["pdf_path"] is None


def test_a_failed_print_shows_a_friendly_message_and_leaves_the_edition_alone(
    client: TestClient, edition, admin, monkeypatch
) -> None:
    async def broken(html: str, day: str) -> bytes:
        raise RuntimeError("chromium crashed")

    monkeypatch.setattr(pdf, "print_html", broken)
    response = client.get(f"/paper/{edition['day']}/pdf")
    assert response.status_code == 503
    assert i18n.t("paper.pdf_busy", "en") in response.text
    assert "Traceback" not in response.text
    assert edition_row(admin, edition["id"])["pdf_path"] is None
    errors = (
        admin.table("agent_activity")
        .select("kind")
        .eq("edition_id", edition["id"])
        .eq("agent", "pdf")
        .eq("kind", "error")
        .execute()
        .data
    )
    assert len(errors) == 1
    assert (
        client.get(f"/paper/{edition['day']}").status_code == 200
    )  # web edition unaffected


def test_health_reports_the_shared_browser_once_the_app_has_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf, "start_on_startup", REAL_START_ON_STARTUP)
    with TestClient(app) as started:
        assert started.get("/health").json()["pdf"] is True


def test_on_a_low_memory_host_chromium_runs_only_while_a_pdf_is_printed(
    client: TestClient, edition, monkeypatch
) -> None:
    monkeypatch.setattr(pdf, "low_memory", lambda: True)
    assert pdf._browser is None  # nothing is kept running between requests
    response = client.get(f"/paper/{edition['day']}/pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert len(response.content) > 20_000
    assert pdf._browser is None  # stopped again as soon as the PDF was printed
    assert pdf._active_renders == 0
