"""Branches that only run with three or more people, or with larger data.

`conftest.py` builds a pair, so none of this is reached there. Everything below
builds `Person` records directly. Each expected value is worked out in the
comment above it.
"""

from __future__ import annotations

import math

from matchcut.metrics import (
    group_agreement,
    hot_takes,
    language_breakdown,
    summary_facts,
)
from matchcut.models import FilmInfo, FilmRef, Group, Person, Thresholds
from matchcut.recommend import from_friends_ratings
from matchcut.render import SECTIONS, bar_chart_svg, build_report, heatmap_svg

from .conftest import make_pair

LOW = Thresholds(min_overlap=2, min_group=2)


def person(
    label: str, ratings: dict[str, float], also_watched: tuple[str, ...] = ()
) -> Person:
    watched = {i: FilmRef(i, f"Film {i}", 2000) for i in [*ratings, *also_watched]}
    return Person(label=label, ratings=dict(ratings), watched=watched)


def trio() -> Group:
    """x, y, z are rated by all three; w by ana and ben only.

        film   ana   ben   cy
        x      5     3     3
        y      5     3     3
        z      5     3     3
        w      4     4     -
    """
    return Group(
        people=[
            person("ana", {"x": 5.0, "y": 5.0, "z": 5.0, "w": 4.0}),
            person("ben", {"x": 3.0, "y": 3.0, "z": 3.0, "w": 4.0}),
            person("cy", {"x": 3.0, "y": 3.0, "z": 3.0}),
        ]
    )


# --------------------------------------------------------------------------
# summary: the "furthest from everyone" tilt sentence
# --------------------------------------------------------------------------


def test_tilt_fact_names_the_person_furthest_from_the_rest():
    """Tilt = own mean minus the others' mean, over films shared with someone.

    ana: mine 5,5,5,4 (4.75) vs others 3,3,3,4 (3.25)  ->  +1.50
    ben: mine 3,3,3,4 (3.25) vs others 4,4,4,4 (4.00)  ->  -0.75
    cy:  mine 3,3,3   (3.00) vs others 4,4,4   (4.00)  ->  -1.00
    """
    facts = summary_facts(trio(), LOW)
    assert (
        "ana sits furthest from everyone else, rating 1.50 stars above the "
        "others on the films they share." in facts
    )


# --------------------------------------------------------------------------
# group agreement
# --------------------------------------------------------------------------


def test_agreement_on_a_trio_uses_the_films_all_three_rated():
    """Only x, y, z are rated by everyone (3 < 20), and the three-rater
    fallback gives the same three. w has two raters and is out. Each has
    spread 5 - 3 = 2.0.

    The `basis` label is left out on purpose: it names which rule produced the
    pool, which is the metrics module's business, not this test's."""
    agreement = group_agreement(trio())
    assert agreement.films_counted == 3
    assert agreement.mean_spread == 2.0


def test_agreement_uses_films_everyone_rated_once_there_are_enough():
    """Twenty films all three rated.

    f00: ana 3, ben 3, cy 5 -> spread 2
    f01..f09: all 3        -> spread 0 (nine films)
    f10..f19: ben 4, others 3 -> spread 1 (ten films)
    Mean spread = (2 + 0 + 10) / 20 = 0.6.
    """
    ids = [f"f{i:02d}" for i in range(20)]
    ana = {i: 3.0 for i in ids}
    ben = {i: (3.0 if n < 10 else 4.0) for n, i in enumerate(ids)}
    cy = {i: 3.0 for i in ids}
    cy["f00"] = 5.0
    group = Group(people=[person("ana", ana), person("ben", ben), person("cy", cy)])

    agreement = group_agreement(group)

    assert agreement.basis == "all"
    assert agreement.films_counted == 20
    assert math.isclose(agreement.mean_spread, 0.6)
    assert agreement.divisive[0].boxd_id == "f00"
    assert agreement.divisive[0].detail == "cy 5 vs ana 3"
    assert len(agreement.unanimous) == 5
    assert all(line.detail == "all within 0" for line in agreement.unanimous)


# --------------------------------------------------------------------------
# hot takes
# --------------------------------------------------------------------------


def test_hot_takes_need_two_others_with_three_people():
    """w is rated by ana and ben only, so for each of them it has one other
    rater and is not a candidate. x, y, z are.

    ana: 5 vs mean(3, 3) = 3.0 -> gap +2.0 on x, y, z; nothing below.
    ben: 3 vs mean(5, 3) = 4.0 -> gap -1.0 on x, y, z; nothing above.
    """
    takes = hot_takes(trio())

    ana = takes["ana"]
    assert ana["min_others"] == 2
    assert ana["candidates"] == 3
    assert [line.boxd_id for line in ana["above"]] == ["x", "y", "z"]
    assert [line.detail for line in ana["above"]] == ["5 vs 3.0"] * 3
    assert ana["below"] == []

    ben = takes["ben"]
    assert ben["candidates"] == 3
    assert ben["above"] == []
    assert [line.detail for line in ben["below"]] == ["3 vs 4.0"] * 3


# --------------------------------------------------------------------------
# recommendations from friends' ratings
# --------------------------------------------------------------------------


def test_friend_picks_need_two_raters_and_a_mean_of_four_and_a_half():
    """cy has only seen s. Of what the others rated that cy has not watched:

    p: ana 5, ben 5  -> two raters, mean 5.0   -> picked
    q: ana 5 only    -> one rater              -> not enough raters
    r: ana 4, ben 4  -> two raters, mean 4.0   -> under 4.5
    """
    group = Group(
        people=[
            person("ana", {"p": 5.0, "q": 5.0, "r": 4.0, "s": 3.0}),
            person("ben", {"p": 5.0, "r": 4.0, "s": 3.0}),
            person("cy", {"s": 3.0}),
        ]
    )

    picks = from_friends_ratings(group)

    assert picks["cy"].min_raters == 2
    (pick,) = picks["cy"].items
    assert pick.boxd_id == "p"
    assert pick.mean_rating == 5.0
    assert pick.who == ["ana 5", "ben 5"]
    # Everyone else has seen p, r and s; q has a single rater.
    assert picks["ana"].items == []
    assert picks["ben"].items == []


# --------------------------------------------------------------------------
# summary: blind spot genre and shared five-star films
# --------------------------------------------------------------------------


def genre_film(boxd_id: str, genre: str) -> FilmInfo:
    return FilmInfo(
        boxd_id=boxd_id,
        title=f"Film {boxd_id}",
        year=2000,
        genres=[genre],
        primary_language="English",
    )


def test_blind_spot_genre_is_one_everyone_rates_below_their_own_average():
    """Each of the three rates d1, d2 (Drama) 2.0 and h1, h2 (Horror) 4.0.

    Overall mean 3.0 for everyone. Drama averages 2.0 (below 3.0, and its two
    rated films meet min_group=2); Horror averages 4.0 (not below).
    """
    ratings = {"d1": 2.0, "d2": 2.0, "h1": 4.0, "h2": 4.0}
    films = {
        "d1": genre_film("d1", "Drama"),
        "d2": genre_film("d2", "Drama"),
        "h1": genre_film("h1", "Horror"),
        "h2": genre_film("h2", "Horror"),
    }
    group = Group(
        people=[person(name, ratings) for name in ("ana", "ben", "cy")], films=films
    )

    facts = summary_facts(group, LOW)

    assert (
        "Everyone rates Drama below their own average, so it is the group's "
        "blind spot." in facts
    )
    assert not any("Horror" in fact for fact in facts)


def test_five_star_fact_lists_three_titles_then_counts_the_rest():
    """g1..g4 are 5 stars for all three, listed in id order."""
    ratings = {f"g{n}": 5.0 for n in range(1, 5)}
    group = Group(people=[person(name, ratings) for name in ("ana", "ben", "cy")])

    facts = summary_facts(group, LOW)

    assert "Everyone gave 5 stars to Film g1, Film g2, Film g3, and 1 more." in facts


# --------------------------------------------------------------------------
# language breakdown: folding into "other"
# --------------------------------------------------------------------------


def test_languages_beyond_the_top_five_fold_into_other():
    """ana watched 2 English films and, per language L1..L7, 7, 6, 5, 4, 3, 2, 1.

    The top five other languages are L1..L5; L6 (2) and L7 (1) fold into
    "other", which is 3 of ana's 30 films. ben watched one English film only,
    so he has no "other" row.
    """
    films: dict[str, FilmInfo] = {}
    ana_watched: dict[str, FilmRef] = {}

    def add(boxd_id: str, language: str) -> None:
        films[boxd_id] = FilmInfo(
            boxd_id=boxd_id,
            title=boxd_id,
            year=2000,
            genres=["Drama"],
            primary_language=language,
        )
        ana_watched[boxd_id] = FilmRef(boxd_id, boxd_id, 2000)

    add("e0", "English")
    add("e1", "English")
    for rank in range(1, 8):
        for n in range(8 - rank):
            add(f"l{rank}_{n}", f"L{rank}")

    ana = Person(label="ana", watched=ana_watched)
    ben = Person(label="ben", watched={"e0": ana_watched["e0"]})
    breakdown = language_breakdown(Group(people=[ana, ben], films=films), Thresholds())

    assert breakdown.keys == ["English", "L1", "L2", "L3", "L4", "L5", "other"]
    rows = {row.key: row for row in breakdown.per_person["ana"]}
    assert sorted(rows) == sorted(breakdown.keys)
    assert rows["other"].watched == 3
    assert math.isclose(rows["other"].share, 3 / 30)
    assert rows["other"].average is None
    assert rows["L1"].watched == 7
    assert "other" not in {row.key for row in breakdown.per_person["ben"]}


# --------------------------------------------------------------------------
# rendering with three labels and unsafe label text
# --------------------------------------------------------------------------


def test_heatmap_with_three_labels_blanks_unscored_pairs_and_escapes_labels():
    labels = ["a<b", "c&d", "e"]
    svg = heatmap_svg(
        labels,
        [
            make_pair(0.5, low_sample=True, a="a<b", b="c&d"),
            make_pair(None, a="a<b", b="e"),
            make_pair(-1.0, a="c&d", b="e"),
        ],
    )

    assert "a&lt;b" in svg and "c&amp;d" in svg
    assert "a<b" not in svg and "c&d" not in svg
    # Symmetric: each pair fills two cells.
    assert svg.count("0.50*") == 2  # low sample is starred
    assert svg.count("-1.00") == 2
    assert svg.count("&#8212;") == 2  # no score -> a dash, not a shade


def test_bar_chart_labels_are_escaped():
    svg = bar_chart_svg({"<script>x</script>": 0.5})
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_report_escapes_a_label_with_markup_in_it(tmp_path):
    """Labels come from the Username column of an uploaded export."""
    group = trio()
    group.people[2].label = "x<&>y"
    out = tmp_path / "report.html"

    build_report(group, LOW, missing_enrichment=0, out_path=out)

    html = out.read_text(encoding="utf-8")
    assert "x<&>y" not in html
    assert "x&lt;&amp;&gt;y" in html
    for section in SECTIONS:
        assert f'id="{section}"' in html
