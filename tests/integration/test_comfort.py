"""Reading comfort: theme and text size are saved per reader and applied to the page (F-20)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.main import app

pytestmark = pytest.mark.integration


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/login")
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def profile(admin, user_id: str) -> dict:
    return admin.table("profiles").select("*").eq("user_id", user_id).execute().data[0]


def test_theme_and_text_size_are_saved_and_applied_to_the_edition(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    response = client.post(
        "/settings/comfort",
        data={"theme": "night", "text_size": "XL"},
        headers=csrf(client),
    )
    assert response.status_code == 204 and response.headers["HX-Refresh"] == "true"
    saved = profile(admin, onboarded_user.id)
    assert (saved["theme"], saved["text_size"]) == ("night", "XL")
    html = client.get("/paper/today").text
    assert 'data-theme="night"' in html and 'data-text-size="XL"' in html


def test_each_choice_can_be_saved_on_its_own(
    client: TestClient, admin, onboarded_user
) -> None:
    client.post("/settings/comfort", data={"theme": "day"}, headers=csrf(client))
    client.post("/settings/comfort", data={"text_size": "S"}, headers=csrf(client))
    saved = profile(admin, onboarded_user.id)
    assert (saved["theme"], saved["text_size"]) == ("day", "S")


def test_the_edition_offers_the_comfort_dialog_with_the_current_choice(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    client.post("/settings/comfort", data={"theme": "day"}, headers=csrf(client))
    html = client.get("/paper/today").text
    assert 'id="comfort"' in html and 'hx-post="/settings/comfort"' in html
    assert 'name="theme" value="day" class="sr-only" checked' in html
    assert 'name="text_size" value="M" class="sr-only" checked' in html
    assert (
        "/paper/" in html and "/pdf" in html and "/print" in html
    )  # Paper view + PDF buttons
    assert "frame-wide" in html  # the desktop layout hook


@pytest.mark.parametrize(
    "data",
    [{"theme": "neon"}, {"text_size": "XXL"}, {"theme": "day", "text_size": "?"}],
)
def test_unknown_values_are_rejected_and_nothing_is_saved(
    client: TestClient, admin, onboarded_user, data: dict
) -> None:
    before = profile(admin, onboarded_user.id)
    assert (
        client.post("/settings/comfort", data=data, headers=csrf(client)).status_code
        == 422
    )
    after = profile(admin, onboarded_user.id)
    assert (after["theme"], after["text_size"]) == (
        before["theme"],
        before["text_size"],
    )


def test_comfort_needs_csrf_and_a_login_and_only_touches_your_own_profile(
    client: TestClient, admin, onboarded_user, make_user, post_form
) -> None:
    assert client.post("/settings/comfort", data={"theme": "night"}).status_code == 403
    anonymous = TestClient(app)
    response = anonymous.post(
        "/settings/comfort",
        data={"theme": "night"},
        headers={**csrf(anonymous), "HX-Request": "true"},
    )
    assert response.status_code == 401
    other = make_user("Other")
    browser = TestClient(app)
    post_form(browser, "/login", email=other.email, password=other.password)
    browser.post("/settings/comfort", data={"theme": "night"}, headers=csrf(browser))
    assert profile(admin, other.id)["theme"] == "night"
    assert profile(admin, onboarded_user.id)["theme"] == "auto"  # untouched
