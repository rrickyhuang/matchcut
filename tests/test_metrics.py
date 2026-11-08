"""Metrics on made-up exports whose answers are worked out by hand.

Ana and Ben share aaa, bbb, ccc, ddd:

    film   ana   ben   gap
    aaa    1.0   3.0   2.0
    bbb    2.0   4.0   2.0
    ccc    3.0   5.0   2.0
    ddd    4.0   2.0  -2.0

So: 4 shared films, mean absolute gap exactly 2.0, nothing within half a star.
Ana additionally rated eee (5.0), which Ben has not seen.
"""

from __future__ import annotations

import math

from matchcut.metrics import (
    calling_cards,
    consensus,
    decade_breakdown,
    genre_breakdown,
    group_agreement,
    hot_takes,
    language_breakdown,
    pair_stats,
    pearson,
    person_stats,
    summary_facts,
)
from matchcut.models import FilmRef, Group, Person, Thresholds


# --------------------------------------------------------------------------
# pearson
# --------------------------------------------------------------------------


def test_pearson_is_one_for_a_constant_offset():
    assert pearson([1.0, 2.0, 3.0], [3.0, 4.0, 5.0]) == 1.0


def test_pearson_is_minus_one_when_perfectly_inverted():
    assert pearson([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == -1.0


def test_pearson_is_none_without_variance():
    """Zero variance is not zero correlation, so the report must show nothing
    rather than 0.00."""
    assert pearson([3.0, 3.0, 3.0], [1.0, 2.0, 3.0]) is None


def test_pearson_is_none_below_two_points():
    assert pearson([4.0], [5.0]) is None


# --------------------------------------------------------------------------
# pairs
# --------------------------------------------------------------------------


def test_pair_stats_uses_only_films_both_rated(group, thresholds):
    (pair,) = pair_stats(group, thresholds)
    assert (pair.a, pair.b) == ("ana", "ben")
    # eee is rated by ana alone, so it is not shared.
    assert pair.shared == 4


def test_pair_closeness_is_exact_on_the_fixture(group, thresholds):
    (pair,) = pair_stats(group, thresholds)
    assert pair.mean_abs_diff == 2.0
    assert pair.within_half_star == 0.0


def test_library_overlap_is_intersection_over_union(group, thresholds):
    (pair,) = pair_stats(group, thresholds)
    # ana watched aaa..eee (5), ben watched aaa..ddd (4); union 5, both 4.
    assert pair.library_overlap == 4 / 5


def test_low_sample_flag_follows_min_overlap(group):
    """The score is still shown -- the spec flags it, never drops it."""
    (pair,) = pair_stats(group, Thresholds(min_overlap=30, min_group=2))
    assert pair.low_sample is True
    assert pair.correlation is not None


def test_pair_is_not_flagged_once_overlap_is_met(group):
    (pair,) = pair_stats(group, Thresholds(min_overlap=4, min_group=2))
    assert pair.low_sample is False


# --------------------------------------------------------------------------
# people
# --------------------------------------------------------------------------


def test_person_stats_counts_and_mean(group):
    ana, ben = person_stats(group)
    assert (ana.rated, ana.watched) == (5, 5)
    assert ana.mean_rating == 3.0  # 1+2+3+4+5 over 5
    assert ana.five_star_count == 1
    assert (ben.rated, ben.watched) == (4, 4)
    assert ben.mean_rating == 3.5  # 3+4+5+2 over 4


def test_tilt_uses_shared_films_only(group):
    """Ana's eee (5.0) must not count: Ben has not rated it.

    On the four shared films Ana averages 2.5 and Ben 3.5.
    """
    ana, ben = person_stats(group)
    assert ana.tilt == -1.0
    assert ben.tilt == 1.0


def test_distribution_sums_to_one(group):
    for stats in person_stats(group):
        assert math.isclose(sum(stats.distribution.values()), 1.0)


def test_distribution_is_a_share_not_a_count(group):
    ana, _ = person_stats(group)
    assert ana.distribution[5.0] == 1 / 5


# --------------------------------------------------------------------------
# agreement and consensus
# --------------------------------------------------------------------------


def test_a_pair_with_few_films_is_still_scored_on_what_they_both_rated(group):
    """Only 4 films are rated by everyone, under AGREEMENT_MIN_FILMS of 20.

    The fallback wants 3 raters per film, which a pair cannot have, so it
    asks for as many as the group has (2). That is the same four films (eee
    has one rater), so nothing fell back and the basis stays "all". Each film
    has spread 2.0, so the mean is 2.0.
    """
    agreement = group_agreement(group)
    assert agreement.basis == "all"
    assert agreement.min_raters == 2
    assert agreement.films_counted == 4
    assert agreement.mean_spread == 2.0


def test_the_basis_falls_back_when_looser_films_really_are_added():
    """Four people, one film all four rated and one only three did: with fewer
    than 20 films the pool widens to the three-rater film, and the basis says
    so."""
    def person(label, ratings):
        return Person(
            label=label,
            ratings=ratings,
            watched={i: FilmRef(i, i, 2000) for i in ratings},
        )

    group = Group(
        people=[
            person("a", {"x": 4.0, "y": 4.0}),
            person("b", {"x": 4.0, "y": 2.0}),
            person("c", {"x": 4.0, "y": 3.0}),
            person("d", {"x": 4.0}),
        ]
    )

    agreement = group_agreement(group)

    assert agreement.basis == "three-plus"
    assert agreement.min_raters == 3
    assert agreement.films_counted == 2  # x (four raters) and y (three)


def test_consensus_ranks_by_group_mean(group):
    result = consensus(group)
    assert result.films_counted == 4
    # ccc: (3+5)/2 = 4.0 is the highest; aaa: (1+3)/2 = 2.0 the lowest.
    assert result.favorites[0].title == "Charlie"
    assert result.favorites[0].value == 4.0
    assert result.lowest[0].title == "Alpha"
    assert result.lowest[0].value == 2.0


# --------------------------------------------------------------------------
# hot takes and calling cards
# --------------------------------------------------------------------------


def test_hot_takes_degrade_to_one_other_for_a_pair(group):
    """The spec's "2 others" rule cannot fire with 2 people."""
    takes = hot_takes(group)
    assert takes["ana"]["min_others"] == 1
    assert takes["ana"]["candidates"] == 4


def test_hot_takes_split_above_and_below(group):
    takes = hot_takes(group)["ana"]
    # ddd is the only film ana rates above ben (4.0 vs 2.0).
    assert [line.title for line in takes["above"]] == ["Delta"]
    assert {line.title for line in takes["below"]} == {"Alpha", "Bravo", "Charlie"}


def test_calling_cards_are_five_stars_nobody_else_watched(group):
    """eee is ana's 5-star film that ben has not watched. aaa is rated 1.0 and
    ddd is watched by ben, so neither qualifies."""
    cards = calling_cards(group)
    assert [line.title for line in cards["ana"]] == ["Echo"]
    assert cards["ben"] == []


# --------------------------------------------------------------------------
# breakdowns
# --------------------------------------------------------------------------


def test_genre_shares_can_exceed_one_film_per_film(group, thresholds):
    """bbb is Drama *and* Comedy, so shares do not sum to 1."""
    rows = {r.key: r for r in genre_breakdown(group, thresholds).per_person["ana"]}
    assert rows["Drama"].watched == 2  # aaa, bbb
    assert rows["Comedy"].watched == 2  # bbb, ccc
    assert rows["Horror"].watched == 2  # ddd, eee
    assert sum(r.share for r in rows.values()) > 1.0


def test_genre_average_is_withheld_below_min_group(group):
    rows = {
        r.key: r
        for r in genre_breakdown(group, Thresholds(min_group=3)).per_person["ana"]
    }
    # Drama has 2 rated films, under the floor of 3.
    assert rows["Drama"].rated == 2
    assert rows["Drama"].average is None


def test_genre_average_is_shown_once_the_floor_is_met(group):
    rows = {
        r.key: r
        for r in genre_breakdown(group, Thresholds(min_group=2)).per_person["ana"]
    }
    assert rows["Drama"].average == 1.5  # aaa 1.0, bbb 2.0


def test_decades_need_no_enrichment(exports_dir, thresholds):
    """The year is in the CSV, so decades work with an empty film cache."""
    from matchcut.exports import load_people

    bare = Group(people=load_people(exports_dir), films={})
    rows = {r.key: r for r in decade_breakdown(bare, thresholds).per_person["ana"]}
    assert rows["2020s"].watched == 2  # ddd, eee
    assert rows["1990s"].watched == 1  # aaa


def test_language_counts_primary_only(group, thresholds):
    rows = {r.key: r for r in language_breakdown(group, thresholds).per_person["ana"]}
    assert rows["English"].watched == 3  # aaa, bbb, ccc
    assert rows["Korean"].watched == 2  # ddd, eee


def test_films_without_enrichment_shrink_the_base(exports_dir, thresholds):
    """A film with no genre data is skipped and counted, not bucketed as
    "unknown" -- so the remaining shares stay honest."""
    from matchcut.exports import load_people

    bare = Group(people=load_people(exports_dir), films={})
    breakdown = genre_breakdown(bare, thresholds)
    assert breakdown.per_person["ana"] == []
    assert breakdown.skipped["ana"] == 5


# --------------------------------------------------------------------------
# summary facts
# --------------------------------------------------------------------------


def test_summary_facts_are_deterministic(group, thresholds):
    assert summary_facts(group, thresholds) == summary_facts(group, thresholds)


def test_summary_mentions_the_closest_pair(group, thresholds):
    facts = summary_facts(group, thresholds)
    assert any("closest pair" in fact for fact in facts)


def test_summary_skips_the_pair_fact_when_every_pair_is_low_sample(group):
    """A flagged pair should not be announced as "the closest pair"."""
    facts = summary_facts(group, Thresholds(min_overlap=30, min_group=2))
    assert not any("closest pair" in fact for fact in facts)


def test_summary_counts_what_everyone_saw(group, thresholds):
    facts = summary_facts(group, thresholds)
    assert any("seen 4 of the same films and rated 4 of them" in f for f in facts)


def test_tilt_fact_is_skipped_when_the_gap_is_small():
    """Under 0.1 stars the sentence does not fire."""
    a = Person(label="a", ratings={"aaa": 3.0, "bbb": 4.0})
    b = Person(label="b", ratings={"aaa": 3.0, "bbb": 4.0})
    a.watched = {k: None for k in a.ratings}
    b.watched = {k: None for k in b.ratings}
    facts = summary_facts(Group(people=[a, b]), Thresholds(min_overlap=2))
    assert not any("stars higher than" in fact for fact in facts)
