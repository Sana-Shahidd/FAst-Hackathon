"""Landing / login / signup pages, language + RTL, CSRF, auth redirects, static files."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.config import SUPPORTED_LANGS, settings
from app.main import app, create_app
from app.services import i18n

pytestmark = pytest.mark.integration


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    assert match, "no csrf_token hidden input on the page"
    return match.group(1)


def test_landing_page_renders_masthead_pitch_and_calls_to_action(
    client: TestClient,
) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'lang="en"' in html and 'dir="ltr"' in html
    assert ">Subah<" in html
    assert i18n.t("app.tagline", "en") in html
    assert i18n.t("landing.pitch", "en") in html
    assert 'href="/signup"' in html and 'href="/login"' in html
    assert "/static/app.css" in html


def test_urdu_page_is_rtl_with_nastaliq_font(client: TestClient) -> None:
    html = client.get("/?lang=ur").text
    assert 'lang="ur"' in html and 'dir="rtl"' in html
    assert '--lang-display: "Noto Nastaliq Urdu"' in html
    assert "family=Noto+Nastaliq+Urdu" in html
    assert i18n.t("landing.pitch", "ur") in html
    assert i18n.t("auth.signup", "ur") in html


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_every_language_renders_with_the_right_direction(
    client: TestClient, lang: str
) -> None:
    html = client.get(f"/login?lang={lang}").text
    assert f'lang="{lang}"' in html
    assert f'dir="{"rtl" if lang in ("ur", "ar") else "ltr"}"' in html
    assert i18n.t("auth.password", lang) in html
    assert f'--lang-ui: "{i18n.languages()[lang]["font_ui"]}"' in html


def test_chosen_language_is_remembered_and_unknown_ones_are_ignored(
    client: TestClient,
) -> None:
    client.get("/?lang=ar")
    assert 'dir="rtl"' in client.get("/login").text  # remembered via cookie
    assert 'lang="en"' in TestClient(app).get("/?lang=xx").text
    assert 'lang="en"' in TestClient(app).get("/?lang=<script>").text


def test_language_chips_link_to_every_edition_language(client: TestClient) -> None:
    html = client.get("/").text
    for code, info in i18n.languages().items():
        assert f'href="/?lang={code}"' in html
        assert info["native"] in html


def test_login_and_signup_forms_carry_a_csrf_token_and_cookie(
    client: TestClient,
) -> None:
    for path, action in (("/login", "/login"), ("/signup", "/signup")):
        response = TestClient(app).get(path)  # a fresh visitor gets the CSRF cookie
        assert response.status_code == 200
        assert f'action="{action}"' in response.text
        assert 'type="password"' in response.text and 'type="email"' in response.text
        assert csrf_from(response.text)
        assert "sb_csrf" in response.headers["set-cookie"]
        assert "httponly" in response.headers["set-cookie"].lower()


def test_posting_without_a_valid_csrf_token_is_forbidden(client: TestClient) -> None:
    client.get("/login")
    body = {"email": "a@b.co", "password": "secret1"}
    assert client.post("/login", data=body).status_code == 403
    assert (
        client.post("/login", data={**body, "csrf_token": "0" * 64}).status_code == 403
    )
    assert client.post("/signup", data=body).status_code == 403
    assert (
        TestClient(app).post("/login", data=body).status_code == 403
    )  # no cookie at all


def test_csrf_token_from_another_session_is_rejected(client: TestClient) -> None:
    token = csrf_from(client.get("/login").text)
    other = TestClient(app)
    other.get("/login")  # gets its own cookie
    response = other.post(
        "/login", data={"email": "a@b.co", "password": "x", "csrf_token": token}
    )
    assert response.status_code == 403


def test_signed_out_visitors_are_sent_to_login(client: TestClient) -> None:
    response = client.get("/paper/today", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_signed_out_fragment_requests_get_401_with_htmx_redirect(
    client: TestClient,
) -> None:
    response = client.get(
        "/paper/today", headers={"HX-Request": "true"}, follow_redirects=False
    )
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login"


def test_static_assets_are_served(client: TestClient) -> None:
    css = client.get("/static/app.css")
    assert (
        css.status_code == 200
        and "--hero" in css.text
        and "text/css" in css.headers["content-type"]
    )
    assert client.get("/static/favicon.svg").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_api_docs_are_hidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TestClient(create_app()).get("/docs").status_code == 200
    monkeypatch.setattr(settings, "APP_ENV", "production")
    prod = TestClient(create_app())
    assert prod.get("/docs").status_code == 404
    assert prod.get("/openapi.json").status_code == 404
    assert prod.get("/health").status_code == 200


def test_bottom_nav_marks_the_active_item() -> None:
    template = deps.templates.get_template("_bottom_nav.html")
    html = template.render(t=lambda key: i18n.t(key, "en"), nav_active="saved")
    assert html.count("<a ") == 4
    assert html.count('aria-current="page"') == 1
    saved = re.search(r'<a [^>]*href="/saved"[^>]*>', html).group(0)
    assert 'aria-current="page"' in saved
    for href in ("/paper/today", "/archive", "/profile"):
        assert f'href="{href}"' in html
