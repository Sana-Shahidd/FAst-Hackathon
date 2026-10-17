"""Learning end to end: signals move weights, the Learner suggests, the reader decides (T-10: F-10, F-11)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.agents import runner
from app.main import app
from app.models import LearnerOut, ParsedInterest
from app.services import edition as pipeline
from app.services import i18n, learning

pytestmark = pytest.mark.integration


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/login")
    return {"X-CSRF-Token": deps._sign(client.cookies.get("sb_csrf"))}


def interests(admin, user_id: str, **match) -> dict[str, dict]:
    query = admin.table("interests").select("*").eq("user_id", user_id)
    for column, value in match.items():
        query = query.eq(column, value)
    return {r["label"]: r for r in query.execute().data}


def weight_of(admin, user_id: str, topic: str) -> float:
    rows = (
        admin.table("interests")
        .select("weight")
        .eq("user_id", user_id)
        .eq("topic_key", topic)
        .execute()
        .data
    )
    return rows[0]["weight"]


def history(admin, interest_id: str) -> list[dict]:
    return (
        admin.table("interest_history")
        .select("old_weight,new_weight,reason")
        .eq("interest_id", interest_id)
        .order("created_at")
        .execute()
        .data
    )


def story(edition: dict, topics: tuple[str, ...]) -> dict:
    return next(
        a
        for a in edition["articles"]
        if a["topic_key"] in topics and a["slot"] != "lead"
    )


def like(client: TestClient, art_id: str, kind: str = "more_like"):
    return client.post(
        "/signals",
        data={"edition_article_id": art_id, "kind": kind},
        headers=csrf(client),
    )


def with_learner(fake_agents, answer):
    """Fake agents for everything, and `answer` for the Learner (None = force the fallback)."""

    async def run(key, factory, prompt, edition_id, **kwargs):
        if key == "learner":
            return answer
        return await fake_agents(key, factory, prompt, edition_id, **kwargs)

    return run


def retopic(admin, edition: dict, count: int, topic: str) -> list[dict]:
    """Make `count` non-lead stories of the edition belong to a topic the reader does not follow."""
    chosen = [a for a in edition["articles"] if a["slot"] != "lead"][:count]
    for art in chosen:
        admin.table("edition_articles").update(
            {"topic_key": topic, "interest_id": None}
        ).eq("id", art["id"]).execute()
    return chosen


# ------------------------------------------------------------------ weights


def test_a_like_and_a_dislike_move_the_stories_interest_and_leave_history(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition, ("pakistan", "climate"))
    topic = art["topic_key"]
    before = weight_of(admin, onboarded_user.id, topic)
    assert like(client, art["id"]).status_code == 200
    assert weight_of(admin, onboarded_user.id, topic) == round(before + 0.15, 2)
    other = next(
        a
        for a in edition["articles"]
        if a["topic_key"] == topic and a["id"] != art["id"]
    )
    like(client, other["id"], "less_like")
    assert weight_of(admin, onboarded_user.id, topic) == before
    row = (
        admin.table("interests")
        .select("id")
        .eq("user_id", onboarded_user.id)
        .eq("topic_key", topic)
        .execute()
        .data[0]
    )
    moves = history(admin, row["id"])
    assert [(m["old_weight"], m["new_weight"], m["reason"]) for m in moves] == [
        (before, round(before + 0.15, 2), "more_like"),
        (round(before + 0.15, 2), before, "less_like"),
    ]


def test_a_repeated_tap_counts_once_and_a_maxed_interest_stays_at_the_ceiling(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition, ("ai",))
    assert weight_of(admin, onboarded_user.id, "ai") == 1.0
    like(client, art["id"])
    like(client, art["id"])
    assert weight_of(admin, onboarded_user.id, "ai") == 1.0
    ai = (
        admin.table("interests")
        .select("id")
        .eq("user_id", onboarded_user.id)
        .eq("topic_key", "ai")
        .execute()
        .data[0]
    )
    assert history(admin, ai["id"]) == []  # nothing changed, so nothing is logged


def test_click_save_and_a_long_dwell_move_weights_by_their_constants(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition, ("pakistan", "climate"))
    topic = art["topic_key"]
    start = weight_of(admin, onboarded_user.id, topic)
    client.get(f"/r/{art['id']}", follow_redirects=False)  # click +0.08
    assert weight_of(admin, onboarded_user.id, topic) == round(start + 0.08, 2)
    client.post(f"/saved/{art['id']}", headers=csrf(client))  # save +0.10
    assert weight_of(admin, onboarded_user.id, topic) == round(start + 0.18, 2)
    client.post(
        "/signals",
        data={"edition_article_id": art["id"], "kind": "dwell", "value": "10"},
        headers=csrf(client),
    )  # too short: no change
    assert weight_of(admin, onboarded_user.id, topic) == round(start + 0.18, 2)
    client.post(
        "/signals",
        data={"edition_article_id": art["id"], "kind": "dwell", "value": "25"},
        headers=csrf(client),
    )  # +0.04
    assert weight_of(admin, onboarded_user.id, topic) == round(start + 0.22, 2)


def test_hiding_a_source_blocks_it_without_touching_weights(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition, ("pakistan", "climate"))
    before = weight_of(admin, onboarded_user.id, art["topic_key"])
    like(client, art["id"], "skip_source")
    blocked = (
        admin.table("blocked_sources")
        .select("source_name")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data
    )
    assert [b["source_name"] for b in blocked] == [art["articles"]["source_name"]]
    assert weight_of(admin, onboarded_user.id, art["topic_key"]) == before


# ------------------------------------------------------------------ Learner


def test_five_likes_make_the_learner_suggest_and_the_reader_accepts(
    client: TestClient, edition, admin, onboarded_user, fake_agents, monkeypatch
) -> None:
    ev = [a for a in retopic(admin, edition, 5, "science")]
    for art in ev[:4]:
        like(client, art["id"])
    assert (
        asyncio.run(learning.maybe_run_learner(onboarded_user.id)) is False
    )  # only 4 signals
    like(client, ev[4]["id"])
    climate_before = weight_of(admin, onboarded_user.id, "climate")
    answer = LearnerOut(
        add=[ParsedInterest(label="Electric vehicles", query='"electric vehicles"')],
        lower=[i18n.t("topic.climate", "en")],
        note="You read a lot about electric cars this week",
    )
    monkeypatch.setattr(runner, "run_agent", with_learner(fake_agents, answer))
    assert (
        asyncio.run(learning.maybe_run_learner(onboarded_user.id, edition["id"]))
        is True
    )

    suggestions = (
        admin.table("suggestions")
        .select("*")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data
    )
    assert [(s["label"], s["status"]) for s in suggestions] == [
        ("Electric vehicles", "pending")
    ]
    notes = (
        admin.table("learner_notes")
        .select("note")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data
    )
    assert [n["note"] for n in notes] == [
        "You read a lot about electric cars this week"
    ]
    assert weight_of(admin, onboarded_user.id, "climate") == round(
        climate_before - 0.1, 2
    )
    unprocessed = (
        admin.table("signals")
        .select("id")
        .eq("user_id", onboarded_user.id)
        .eq("processed_by_learner", False)
        .in_("kind", ["more_like"])
        .execute()
        .data
    )
    assert unprocessed == []
    assert (
        asyncio.run(learning.maybe_run_learner(onboarded_user.id)) is False
    )  # nothing new to learn from

    page = client.get("/paper/today").text
    assert 'id="suggestion-card"' in page and "Electric vehicles" in page
    assert "You read a lot about electric cars this week" in page
    suggestion = suggestions[0]
    response = client.post(
        f"/suggestions/{suggestion['id']}",
        data={"decision": "accept"},
        headers=csrf(client),
    )
    assert response.status_code == 200 and response.text == ""
    added = interests(admin, onboarded_user.id)["Electric vehicles"]
    assert (added["weight"], added["source"], added["active"]) == (0.5, "learned", True)
    status = (
        admin.table("suggestions")
        .select("status")
        .eq("id", suggestion["id"])
        .execute()
        .data
    )
    assert status[0]["status"] == "accepted"
    assert 'id="suggestion-card"' not in client.get("/paper/today").text
    assert "Electric vehicles" in client.get("/profile").text


def test_rejecting_a_suggestion_remembers_it_and_it_is_not_suggested_again(
    client: TestClient, edition, admin, onboarded_user, fake_agents, monkeypatch
) -> None:
    for art in retopic(admin, edition, 5, "science"):
        like(client, art["id"])
    answer = LearnerOut(
        add=[ParsedInterest(label="Space race", query='"space race"')],
        lower=[],
        note="n",
    )
    monkeypatch.setattr(runner, "run_agent", with_learner(fake_agents, answer))
    asyncio.run(learning.maybe_run_learner(onboarded_user.id))
    suggestion = (
        admin.table("suggestions")
        .select("id")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data[0]
    )
    client.post(
        f"/suggestions/{suggestion['id']}",
        data={"decision": "reject"},
        headers=csrf(client),
    )
    assert "Space race" not in interests(admin, onboarded_user.id)
    assert (
        client.post(
            f"/suggestions/{suggestion['id']}",
            data={"decision": "accept"},
            headers=csrf(client),
        ).status_code
        == 404
    )  # already decided
    later = [a for a in edition["articles"] if a["slot"] != "lead"][5:10]
    for art in later:
        like(client, art["id"])
    asyncio.run(learning.maybe_run_learner(onboarded_user.id))
    labels = [
        s["label"]
        for s in admin.table("suggestions")
        .select("label")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data
    ]
    assert labels.count("Space race") == 1


def test_the_next_edition_runs_the_learner_and_falls_back_to_counting_topics(
    client: TestClient, edition, admin, onboarded_user, fake_agents, monkeypatch
) -> None:
    for art in retopic(admin, edition, 5, "science"):
        like(client, art["id"])
    monkeypatch.setattr(runner, "run_agent", with_learner(fake_agents, None))
    tomorrow = date.fromisoformat(edition["day"]) + timedelta(days=1)
    next_id = asyncio.run(pipeline.generate_edition(onboarded_user.id, tomorrow))
    pending = (
        admin.table("suggestions")
        .select("label,status")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data
    )
    assert [(s["label"], s["status"]) for s in pending] == [
        (i18n.t("topic.science", "en"), "pending")
    ]
    steps = (
        admin.table("agent_activity")
        .select("agent,kind,message")
        .eq("edition_id", next_id)
        .eq("agent", "learner")
        .execute()
        .data
    )
    assert steps and any(s["kind"] in ("decision", "fallback") for s in steps)
    assert admin.table("learner_notes").select("note").eq(
        "user_id", onboarded_user.id
    ).execute().data[0]["note"] == i18n.t("learner.default", "en")
    assert 'id="suggestion-card"' in client.get(f"/paper/{tomorrow}").text


def test_a_stranger_cannot_decide_your_suggestion(
    client: TestClient, edition, admin, onboarded_user, make_user, post_form
) -> None:
    admin.table("suggestions").insert(
        {"user_id": onboarded_user.id, "label": "Chess", "query": "chess"}
    ).execute()
    suggestion = (
        admin.table("suggestions")
        .select("id")
        .eq("user_id", onboarded_user.id)
        .execute()
        .data[0]
    )
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    response = browser.post(
        f"/suggestions/{suggestion['id']}",
        data={"decision": "accept"},
        headers=csrf(browser),
    )
    assert response.status_code == 404
    assert interests(admin, stranger.id) == {}
    assert (
        client.post(
            "/suggestions/not-a-uuid", data={"decision": "accept"}, headers=csrf(client)
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/suggestions/{suggestion['id']}",
            data={"decision": "maybe"},
            headers=csrf(client),
        ).status_code
        == 422
    )


# ------------------------------------------------------------------ profile


def test_the_profile_shows_interests_as_bars_with_history(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    art = story(edition, ("pakistan", "climate"))
    like(client, art["id"])
    html = client.get("/profile").text
    assert (
        i18n.t("profile.interests", "en") in html
        and i18n.t("profile.learned", "en") in html
    )
    assert (
        i18n.t("learner.default", "en").replace("'", "&#39;") in html
    )  # no note yet (apostrophe is escaped)
    for topic in ("ai", "pakistan", "climate"):
        assert i18n.t(f"topic.{topic}", "en") in html
    assert 'class="interest-bar"' in html and 'type="range"' in html
    assert html.count("<polyline") == 3
    assert "100%" in html  # AI is at the ceiling
    assert 'aria-current="page"' in html


def test_the_reader_can_set_remove_and_add_interests(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    rows = interests(admin, onboarded_user.id)
    pakistan = rows[i18n.t("topic.pakistan", "en")]
    done = client.post(
        "/interests",
        data={"action": "update", "interest_id": pakistan["id"], "weight": "0.3"},
        headers=csrf(client),
    )
    assert (
        done.status_code == 200
        and 'id="profile-body"' in done.text
        and "<html" not in done.text
    )
    assert (
        interests(admin, onboarded_user.id)[i18n.t("topic.pakistan", "en")]["weight"]
        == 0.3
    )
    assert history(admin, pakistan["id"])[-1]["reason"] == "manual"
    client.post(
        "/interests",
        data={"action": "update", "interest_id": pakistan["id"], "weight": "7"},
        headers=csrf(client),
    )
    assert (
        interests(admin, onboarded_user.id)[i18n.t("topic.pakistan", "en")]["weight"]
        == 1.0
    )  # clamped

    climate = rows[i18n.t("topic.climate", "en")]
    client.post(
        "/interests",
        data={"action": "delete", "interest_id": climate["id"]},
        headers=csrf(client),
    )
    assert i18n.t("topic.climate", "en") not in interests(admin, onboarded_user.id)

    client.post(
        "/interests", data={"action": "add", "label": "Formula E"}, headers=csrf(client)
    )
    added = interests(admin, onboarded_user.id)["Formula E"]
    assert (added["weight"], added["source"]) == (0.6, "custom")
    assert "Formula E" in client.get("/profile").text
    assert (
        client.post(
            "/interests", data={"action": "add", "label": "x"}, headers=csrf(client)
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/interests", data={"action": "explode"}, headers=csrf(client)
        ).status_code
        == 422
    )


def test_interests_and_the_profile_are_private(
    client: TestClient, edition, admin, onboarded_user, make_user, post_form
) -> None:
    mine = next(iter(interests(admin, onboarded_user.id).values()))
    anonymous = TestClient(app).get("/profile", follow_redirects=False)
    assert (anonymous.status_code, anonymous.headers["location"]) == (303, "/login")
    stranger = make_user("Stranger")
    browser = TestClient(app)
    post_form(browser, "/login", email=stranger.email, password=stranger.password)
    assert (
        browser.get("/profile", follow_redirects=False).headers["location"]
        == "/onboarding"
    )
    assert (
        client.post(
            "/interests", data={"action": "delete", "interest_id": mine["id"]}
        ).status_code
        == 403
    )
    assert interests(admin, onboarded_user.id)[mine["label"]]["id"] == mine["id"]


# ------------------------------------------------------------------ nightly


def test_the_nightly_job_nudges_ignored_stories_down_and_retires_long_low_interests(
    client: TestClient, edition, admin, onboarded_user
) -> None:
    today = datetime.now(UTC).date()
    old_day = (today - timedelta(days=4)).isoformat()
    admin.table("editions").update({"edition_date": old_day}).eq(
        "id", edition["id"]
    ).execute()
    opened = story(edition, ("pakistan", "climate"))
    client.get(
        f"/paper/{old_day}/a/{opened['id']}"
    )  # one story was read: it must not be punished
    admin.table("interests").insert(
        {
            "user_id": onboarded_user.id,
            "label": "Forgotten",
            "query": "forgotten",
            "weight": 0.08,
            "low_since": (datetime.now(UTC) - timedelta(days=8)).isoformat(),
        }
    ).execute()
    result = asyncio.run(learning.nightly_decay(onboarded_user.id))
    assert result["ignored"] == len(edition["articles"]) - 1
    assert result["deactivated"] == 1
    assert interests(admin, onboarded_user.id)["Forgotten"]["active"] is False
    reasons = {
        h["reason"]
        for row in interests(admin, onboarded_user.id).values()
        for h in history(admin, row["id"])
    }
    assert "ignored" in reasons
    again = asyncio.run(learning.nightly_decay(onboarded_user.id))
    assert again["ignored"] == 0  # every story is punished at most once
