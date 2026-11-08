"""`Group.title_of`: one place that decides what a film is called."""

from __future__ import annotations

from matchcut.models import FilmInfo, FilmRef, Group, Person


def test_title_prefers_the_enriched_record():
    group = Group(
        people=[Person(label="a", watched={"x": FilmRef("x", "Export Name", 1999)})],
        films={"x": FilmInfo(boxd_id="x", title="Page Title", year=2000)},
    )
    assert group.title_of("x") == ("Page Title", 2000)


def test_title_is_kept_for_a_film_that_failed_to_parse():
    """`enriched()` hides non-ok records; the title is still the page's."""
    info = FilmInfo(boxd_id="x", title="Page Title", year=2000, status="unparsed")
    group = Group(people=[Person(label="a")], films={"x": info})
    assert group.enriched("x") is None
    assert group.title_of("x") == ("Page Title", 2000)


def test_title_falls_back_to_the_export_then_a_watchlist_then_the_id():
    seen = Person(label="a", watched={"x": FilmRef("x", "Watched Name", 1999)})
    wanted = Person(label="b", watchlist={"y": FilmRef("y", "Listed Name", None)})
    group = Group(people=[seen, wanted])
    assert group.title_of("x") == ("Watched Name", 1999)
    assert group.title_of("y") == ("Listed Name", None)
    assert group.title_of("zzz") == ("zzz", None)
