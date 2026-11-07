"""Enrichment: page parsing against a saved page, and the cache round trip.

The live site is never contacted here. `film_page.html` is a real Letterboxd
film page saved once, so a layout change shows up as a failure rather than as
silently empty genre and language columns.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from matchcut.enrich import load_cache, parse_film_page, save_cache
from matchcut.models import FilmInfo, FilmRef

FIXTURE = Path(__file__).parent / "fixtures" / "film_page.html"


@pytest.fixture(scope="module")
def page() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(page: str) -> FilmInfo:
    return parse_film_page(page, "zld0", fallback=FilmRef("zld0", "Challengers", 2024))


def test_title_is_the_film_not_the_site(parsed):
    """The page's first `<h1>` is the Letterboxd logo; the film title is
    `h1.primaryname`."""
    assert parsed.title == "Challengers"


def test_year_and_slug(parsed):
    assert parsed.year == 2024
    assert parsed.slug == "challengers"


def test_genres_exclude_themes(parsed):
    """Genres and Themes sit in the same panel, so the heading has to match."""
    assert parsed.genres == ["Romance", "Drama"]


def test_primary_language_is_not_the_spoken_list(parsed):
    """A film counts under its primary language only, so Romanian must not
    become this film's language."""
    assert parsed.primary_language == "English"
    assert parsed.spoken_languages == ["English", "Romanian"]


def test_tmdb_id_comes_off_the_body_tag(parsed):
    assert parsed.tmdb_id == "937287"


def test_parsed_page_is_ok_and_stamped(parsed):
    assert parsed.status == "ok"
    assert parsed.fetched_at is not None


def test_decade_is_derived_from_the_year(parsed):
    assert parsed.decade == 2020


def test_unrecognisable_page_still_yields_a_record():
    """A redirect or an error page must not crash the run."""
    info = parse_film_page(
        "<html><body><p>nothing here</p></body></html>",
        "xxxx",
        fallback=FilmRef("xxxx", "Fallback Title", 1999),
    )
    assert info.title == "Fallback Title"
    assert info.year == 1999
    assert info.genres == []
    assert info.primary_language is None


def test_cache_round_trip(tmp_path, parsed):
    path = tmp_path / "cache" / "films.json"
    save_cache(path, {"zld0": parsed})
    loaded = load_cache(path)
    assert loaded["zld0"] == parsed


def test_cache_stores_only_ok_records(tmp_path, parsed):
    """A failure is worth retrying next run, so it is not written."""
    path = tmp_path / "films.json"
    failed = FilmInfo(boxd_id="bad1", title="Nope", year=None, status="missing")
    save_cache(path, {"zld0": parsed, "bad1": failed})
    assert set(load_cache(path)) == {"zld0"}


def test_saving_keeps_films_that_are_not_in_this_run(tmp_path, parsed):
    """A run over a different group, or a blocked --refresh-cache run, only
    knows about some films; saving must not delete the rest."""
    path = tmp_path / "films.json"
    other = FilmInfo(boxd_id="old1", title="Older", year=1990, genres=["Drama"])
    save_cache(path, {"old1": other})
    save_cache(path, {"zld0": parsed})
    assert set(load_cache(path)) == {"old1", "zld0"}


def test_saving_replaces_a_stored_record_with_a_new_ok_one(tmp_path, parsed):
    path = tmp_path / "films.json"
    stale = FilmInfo(boxd_id="zld0", title="Stale", year=2024)
    save_cache(path, {"zld0": stale})
    save_cache(path, {"zld0": parsed})
    assert load_cache(path)["zld0"].title == "Challengers"


def test_a_failed_refetch_does_not_erase_the_stored_record(tmp_path, parsed):
    path = tmp_path / "films.json"
    save_cache(path, {"zld0": parsed})
    failed = FilmInfo(boxd_id="zld0", title="Nope", year=None, status="error: X")
    save_cache(path, {"zld0": failed})
    assert load_cache(path)["zld0"] == parsed


def test_missing_cache_is_empty_not_an_error(tmp_path):
    assert load_cache(tmp_path / "absent.json") == {}


def test_corrupt_cache_is_empty_not_an_error(tmp_path):
    path = tmp_path / "films.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_cache(path) == {}


def test_cache_is_written_atomically(tmp_path, parsed):
    """No `.tmp` file should survive a successful write."""
    path = tmp_path / "films.json"
    save_cache(path, {"zld0": parsed})
    assert list(p.name for p in tmp_path.iterdir()) == ["films.json"]


def test_cache_is_json_with_a_version(tmp_path, parsed):
    path = tmp_path / "films.json"
    save_cache(path, {"zld0": parsed})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["films"]["zld0"]["tmdb_id"] == "937287"
