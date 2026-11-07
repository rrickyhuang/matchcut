"""Recommendations, and the end-to-end build from fixtures."""

from __future__ import annotations

from matchcut.recommend import from_friends_ratings, from_watchlists
from matchcut.render import SECTIONS, build_report
from matchcut.models import Thresholds


# --------------------------------------------------------------------------
# recommendations
# --------------------------------------------------------------------------


def test_friend_picks_only_suggest_unwatched_films(group):
    """Ben has not seen eee, which Ana rated 5.0."""
    picks = from_friends_ratings(group)
    assert [r.title for r in picks["ben"].items] == ["Echo"]


def test_friend_picks_respect_the_rating_floor(group):
    """Ana has seen everything Ben rated, and nothing Ben rated clears 4.5
    among films she has not seen."""
    picks = from_friends_ratings(group)
    assert picks["ana"].items == []


def test_friend_picks_degrade_to_one_rater_for_a_pair(group):
    picks = from_friends_ratings(group)
    assert picks["ben"].min_raters == 1


def test_friend_picks_name_who_vouched(group):
    (pick,) = from_friends_ratings(group)["ben"].items
    assert pick.who == ["ana 5"]


def test_watchlist_picks_need_two_watchlists_and_nobody_watching(group):
    """fff is on both watchlists and watched by neither."""
    picks = from_watchlists(group)
    assert [r.title for r in picks] == ["Foxtrot"]
    assert picks[0].who == ["ana", "ben"]


def test_watchlist_picks_exclude_films_someone_has_seen(group):
    """aaa is on nobody's watchlist, but prove the watched filter directly by
    putting a watched film on both lists."""
    for person in group.people:
        person.watchlist["aaa"] = person.watched["aaa"]
    assert [r.title for r in from_watchlists(group)] == ["Foxtrot"]


# --------------------------------------------------------------------------
# end to end
# --------------------------------------------------------------------------


def test_build_report_writes_every_section(group, thresholds, tmp_path):
    out = tmp_path / "report.html"
    build_report(group, thresholds, missing_enrichment=0, out_path=out)
    html = out.read_text(encoding="utf-8")
    for section in SECTIONS:
        assert f'id="{section}"' in html, f"missing section {section}"


def test_report_makes_no_external_requests(group, thresholds, tmp_path):
    """One self-contained file: no fonts, scripts, images or stylesheets."""
    out = tmp_path / "report.html"
    build_report(group, thresholds, missing_enrichment=0, out_path=out)
    html = out.read_text(encoding="utf-8")
    for forbidden in ("http://", "https://", "<script", "<img", "@import", "src="):
        assert forbidden not in html, f"report reaches outside: {forbidden}"


def test_report_names_everyone(group, thresholds, tmp_path):
    out = tmp_path / "report.html"
    build_report(group, thresholds, missing_enrichment=0, out_path=out)
    html = out.read_text(encoding="utf-8")
    assert "ana" in html and "ben" in html


def test_partial_report_says_how_many_films_are_missing(group, thresholds, tmp_path):
    out = tmp_path / "report.html"
    build_report(group, thresholds, missing_enrichment=7, out_path=out)
    html = out.read_text(encoding="utf-8")
    assert "Partial report" in html
    assert "7 films" in html


def test_complete_report_does_not_claim_to_be_partial(group, thresholds, tmp_path):
    out = tmp_path / "report.html"
    build_report(group, thresholds, missing_enrichment=0, out_path=out)
    assert "Partial report" not in out.read_text(encoding="utf-8")


def test_report_carries_no_methodology(group, thresholds, tmp_path):
    """Methodology lives in the README. The report holds data and short
    sample-size labels only."""
    out = tmp_path / "report.html"
    build_report(group, thresholds, missing_enrichment=0, out_path=out)
    html = out.read_text(encoding="utf-8").lower()
    assert "pearson" not in html


def test_report_is_byte_identical_across_runs(group, thresholds, tmp_path):
    """Deterministic wording: same exports, same file."""
    first = tmp_path / "a.html"
    second = tmp_path / "b.html"
    build_report(group, thresholds, 0, first)
    build_report(group, thresholds, 0, second)
    assert first.read_bytes() == second.read_bytes()


def test_report_survives_an_empty_film_cache(exports_dir, thresholds, tmp_path):
    """With no enrichment the genre and language sections empty out, but the
    report still builds."""
    from matchcut.exports import load_people
    from matchcut.models import Group

    bare = Group(people=load_people(exports_dir), films={})
    out = tmp_path / "report.html"
    build_report(bare, thresholds, missing_enrichment=5, out_path=out)
    html = out.read_text(encoding="utf-8")
    for section in SECTIONS:
        assert f'id="{section}"' in html


def test_low_sample_pairs_are_labelled_in_the_report(group, tmp_path):
    out = tmp_path / "report.html"
    build_report(group, Thresholds(min_overlap=30, min_group=2), 0, out)
    assert "low sample" in out.read_text(encoding="utf-8")
