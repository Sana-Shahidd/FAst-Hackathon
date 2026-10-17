"""Curator/Editor output validation: unknown ids, top-up, gap filling, length limits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.agents import curator, editor
from app.models import Candidate, CuratorOut, EditorOut, Pick, Reader, WrittenArticle
from app.services import i18n

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 17, 6, 0, tzinfo=UTC)
_n = 0


def cand(
    *,
    topic="ai",
    source="Wire",
    age=2,
    favorite=False,
    summary="",
    title=None,
    lang="en",
) -> Candidate:
    global _n
    _n += 1
    return Candidate(
        url=f"https://news.example.com/v{_n}",
        title=title or f"Headline number {_n}",
        source_name=source,
        summary=summary,
        published_at=NOW - timedelta(hours=age),
        topic_key=topic,
        favorite=favorite,
        lang=lang,
    )


def reader(**kw) -> Reader:
    base = {
        "n": 4,
        "weights": {"ai": 0.8, "pakistan": 0.6},
        "labels": {"ai": "AI", "pakistan": "Pakistan"},
    }
    return Reader(**{**base, **kw})


def pk(c: Candidate, importance: int = 5, section: str | None = None) -> Pick:
    return Pick(
        candidate_id=c.id,
        section=section or c.section,
        importance=importance,
        reason="why",
    )


def pool(count: int = 10) -> list[Candidate]:
    return [
        cand(source=f"S{i}", age=i + 1, topic="ai" if i % 2 else "pakistan")
        for i in range(count)
    ]


# -------------------------------------------------------------- Curator output


def test_unknown_and_duplicate_ids_are_dropped_then_topped_up() -> None:
    cands = pool()
    out = CuratorOut(
        picks=[
            pk(cands[0], 9),
            Pick(candidate_id="made-up-id", section="ai", importance=7, reason="x"),
            pk(cands[0], 8),  # the same story twice
            pk(cands[1], 6),
        ],
        notes="",
    )
    picks = curator.validate_picks(out, cands, reader(), 4, NOW)
    ids = [p.candidate_id for p in picks]
    assert len(picks) == 4 and len(set(ids)) == 4
    assert "made-up-id" not in ids
    assert ids[:2] == [cands[0].id, cands[1].id]  # the valid picks keep their place
    assert all(i in {c.id for c in cands} for i in ids)


def test_blocked_sources_returned_by_the_model_are_dropped() -> None:
    cands = pool()
    bad = cand(source="Tabloid", age=0)
    out = CuratorOut(
        picks=[
            pk(bad, 10),
            pk(cands[0], 8),
            pk(cands[1], 7),
            pk(cands[2], 6),
            pk(cands[3], 5),
        ],
        notes="",
    )
    picks = curator.validate_picks(
        out, [*cands, bad], reader(blocked_sources=["Tabloid"]), 4, NOW
    )
    assert bad.id not in {p.candidate_id for p in picks}


def test_extra_picks_beyond_n_are_cut() -> None:
    cands = pool()
    out = CuratorOut(picks=[pk(c, 5) for c in cands[:8]], notes="")
    assert len(curator.validate_picks(out, cands, reader(), 4, NOW)) == 4


def test_an_unknown_section_is_replaced_by_the_stories_own_section() -> None:
    cands = pool()
    out = CuratorOut(
        picks=[pk(cands[0], 9, section="totally-made-up")]
        + [pk(c) for c in cands[1:4]],
        notes="",
    )
    picks = curator.validate_picks(out, cands, reader(), 4, NOW)
    assert picks[0].section == cands[0].section


def test_exactly_one_lead_even_when_the_model_gives_several_or_none() -> None:
    cands = pool()
    many = CuratorOut(picks=[pk(c, 10) for c in cands[:4]], notes="")
    assert [
        p.importance for p in curator.validate_picks(many, cands, reader(), 4, NOW)
    ].count(10) == 1
    none = CuratorOut(
        picks=[pk(cands[0], 7), pk(cands[1], 9), pk(cands[2], 8), pk(cands[3], 6)],
        notes="",
    )
    got = curator.validate_picks(none, cands, reader(), 4, NOW)
    assert [p.importance for p in got].count(10) == 1
    assert (
        next(p for p in got if p.importance == 10).candidate_id == cands[1].id
    )  # the strongest


def test_a_fresh_favorite_is_added_when_the_model_ignored_favorites() -> None:
    cands = pool()
    fav = cand(source="My Outlet", favorite=True, age=3)
    out = CuratorOut(picks=[pk(c, 8) for c in cands[:4]], notes="")
    picks = curator.validate_picks(out, [*cands, fav], reader(), 4, NOW)
    assert fav.id in {p.candidate_id for p in picks} and len(picks) == 4


async def test_pick_uses_the_agent_result_when_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cands = pool()

    async def fake(key, factory, input, edition_id, **_):
        assert key == "curator" and "<candidates>" in input
        return CuratorOut(
            picks=[pk(c, 8) for c in cands[:4]], notes="Strong day for AI"
        )

    monkeypatch.setattr(curator.runner, "run_agent", fake)
    picks, used_fallback, notes = await curator.pick(cands, reader(), None, NOW)
    assert (len(picks), used_fallback, notes) == (4, False, "Strong day for AI")


@pytest.mark.parametrize("result", [None, CuratorOut(picks=[], notes="")])
async def test_pick_falls_back_to_scoring_when_the_agent_fails(
    monkeypatch: pytest.MonkeyPatch, result: object
) -> None:
    async def fake(*_a, **_k):
        return result

    monkeypatch.setattr(curator.runner, "run_agent", fake)
    picks, used_fallback, _ = await curator.pick(pool(), reader(), None, NOW)
    assert used_fallback is True and len(picks) == 4


# --------------------------------------------------------------- Editor output


def make_picks(cands: list[Candidate]) -> list[Pick]:
    return [pk(c, 10 - i) for i, c in enumerate(cands)]


def written(
    c: Candidate,
    headline="Fresh headline",
    summary="A fresh summary.",
    why="Because you follow AI",
) -> WrittenArticle:
    return WrittenArticle(
        candidate_id=c.id, headline=headline, summary=summary, why=why
    )


def test_a_complete_editor_output_is_used_as_written() -> None:
    cands = pool(4)
    out = EditorOut(
        lead_headline="Big lead",
        lead_dek="Dek line",
        articles=[written(c, f"H{i}") for i, c in enumerate(cands)],
        section_titles={"ai": "Artificial Intelligence", "pakistan": "Pakistan Today"},
        three_things=["one", "two", "three"],
        editor_note="Good morning Sana",
    )
    got = editor.finalize(out, make_picks(cands), {c.id: c for c in cands}, reader())
    assert (got.lead_headline, got.lead_dek, got.editor_note) == (
        "Big lead",
        "Dek line",
        "Good morning Sana",
    )
    assert got.articles[cands[0].id][0] == "H0" and got.three_things == [
        "one",
        "two",
        "three",
    ]
    assert got.section_titles["ai"] == "Artificial Intelligence"
    assert got.used_fallback is False and got.gaps == []


def test_no_editor_output_gives_a_complete_fallback_edition() -> None:
    cands = [
        cand(
            summary="First sentence here. Second sentence here. Third one.",
            title="Original title",
        )
    ] + pool(3)
    got = editor.finalize(None, make_picks(cands), {c.id: c for c in cands}, reader())
    headline, summary, why = got.articles[cands[0].id]
    assert headline == "Original title"
    assert (
        summary == "First sentence here. Second sentence here."
    )  # first two sentences
    assert why == i18n.t("why.topic", "en", topic="AI")
    assert got.editor_note == i18n.t("note.default", "en")
    assert got.three_things == [
        got.articles[c.id][0] for c in cands[:3]
    ]  # top 3 headlines
    assert got.lead_headline == "Original title" and got.used_fallback is True
    assert got.section_titles == {
        "ai": i18n.t("topic.ai", "en"),
        "pakistan": i18n.t("topic.pakistan", "en"),
    }


def test_only_the_missing_articles_are_filled_by_the_fallback() -> None:
    cands = pool(4)
    out = EditorOut(
        lead_headline="L",
        lead_dek="D",
        articles=[
            written(cands[0], "Model headline"),
            written(cands[2], "", ""),
        ],  # 2 blank, 1 and 3 absent
        three_things=["a", "b", "c"],
    )
    got = editor.finalize(out, make_picks(cands), {c.id: c for c in cands}, reader())
    assert got.articles[cands[0].id][0] == "Model headline"
    assert got.articles[cands[1].id][0] == cands[1].title[:110]
    assert got.articles[cands[2].id][0] == cands[2].title[:110]
    assert set(got.gaps) == {cands[1].id, cands[2].id, cands[3].id}
    assert got.used_fallback is True


def test_thin_summaries_fall_back_to_the_read_original_line() -> None:
    c = cand(summary="", source="Dawn")
    got = editor.finalize(None, [pk(c, 10)], {c.id: c}, reader())
    assert got.articles[c.id][1] == i18n.t("article.read_original", "en", source="Dawn")


def test_html_in_model_text_is_stripped_and_unknown_ids_ignored() -> None:
    cands = pool(4)
    stray = WrittenArticle(
        candidate_id="not-a-pick", headline="Ghost", summary="Ghost story", why=""
    )
    out = EditorOut(
        lead_headline="<b>Bold</b> lead",
        lead_dek="Dek <script>alert(1)</script>",
        articles=[written(cands[0], "<i>Italic</i> headline", "<p>Para</p>"), stray],
        three_things=["<b>x</b>", "y", "z"],
    )
    got = editor.finalize(out, make_picks(cands), {c.id: c for c in cands}, reader())
    assert got.lead_headline == "Bold lead"
    assert got.articles[cands[0].id][:2] == ("Italic headline", "Para")
    assert "Ghost" not in str(got.articles)
    assert got.three_things[0] == "x"
    assert got.lead_dek == "Dek"  # <script> content is dropped, not kept as text


def test_blank_three_things_fall_back_to_the_top_headlines() -> None:
    cands = pool(4)
    out = EditorOut(
        lead_headline="L",
        lead_dek="D",
        articles=[written(c, f"H{i}") for i, c in enumerate(cands)],
        three_things=["a", " ", "c"],
    )
    got = editor.finalize(out, make_picks(cands), {c.id: c for c in cands}, reader())
    assert got.three_things == ["H0", "H1", "H2"]


def test_section_titles_fall_back_to_translations_and_interest_labels() -> None:
    cands = [
        cand(topic="ai"),
        cand(topic=None),
        cand(topic="your_city"),
        cand(topic=None),
    ]
    cands[1].interest_id = "abcdef12-0"
    r = reader(lang="ur", labels={"i_abcdef12": "F1 racing"})
    picks = [pk(c, 9 - i) for i, c in enumerate(cands)]
    got = editor.finalize(None, picks, {c.id: c for c in cands}, r)
    assert got.section_titles["ai"] == i18n.t("topic.ai", "ur")
    assert got.section_titles["i_abcdef12"] == "F1 racing"
    assert got.section_titles["your_city"] == i18n.t("paper.your_city", "ur")
    assert got.section_titles["world"] == i18n.t("paper.world", "ur")


def test_overlong_model_text_is_trimmed_not_rejected() -> None:
    out = EditorOut(
        lead_headline="h" * 300,
        lead_dek="d" * 500,
        articles=[
            WrittenArticle(
                candidate_id="x", headline="t" * 400, summary="s" * 900, why="w" * 300
            )
        ],
        three_things=["a" * 300, "b", "c", "d"],
        editor_note="n" * 900,
    )
    assert (
        len(out.lead_headline) == 110
        and len(out.lead_dek) == 240
        and len(out.editor_note) == 240
    )
    art = out.articles[0]
    assert (len(art.headline), len(art.summary), len(art.why)) == (110, 420, 100)
    assert len(out.three_things) == 3 and len(out.three_things[0]) == 120


def test_too_few_three_things_is_still_rejected() -> None:
    with pytest.raises(ValidationError):
        EditorOut(
            lead_headline="L", lead_dek="D", articles=[], three_things=["only one"]
        )


def test_pick_importance_is_clamped_into_range() -> None:
    assert (
        Pick(candidate_id="a", section="ai", importance=42, reason="r").importance == 10
    )
    assert (
        Pick(candidate_id="a", section="ai", importance=-3, reason="r").importance == 1
    )


async def test_write_falls_back_completely_when_the_agent_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cands = pool(4)

    async def fake(*_a, **_k):
        return None

    monkeypatch.setattr(editor.runner, "run_agent", fake)
    got, out = await editor.write(
        make_picks(cands), {c.id: c for c in cands}, reader(), None, NOW.date()
    )
    assert out is None and got.used_fallback is True and len(got.articles) == 4


def test_editor_prompt_contains_only_feed_facts_and_is_escaped() -> None:
    c = cand(title="<script>x</script> Title", summary="Sum & more", source="Dawn")
    text = editor.build_input(reader(name="Sana"), [pk(c, 10)], {c.id: c}, NOW.date())
    assert "reader_name: Sana" in text and "date: 2026-10-17" in text
    assert "<script>" not in text and "&lt;script&gt;x&lt;/script&gt; Title" in text
    assert f'<article id="{c.id}" section="ai" importance="10">' in text
    assert "@" not in text  # no emails or user ids are ever sent to the model
