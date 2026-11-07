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
    # Nothing on the page is a film page, so it must not count as parsed.
    assert info.status == "unparsed"


def test_film_with_no_genres_is_still_ok():
    """A real film page can list no genres; only a page with none of the film
    page's structure is unparsed."""
    info = parse_film_page(
        '<html><body><h1 class="primaryname">Obscure</h1></body></html>',
        "xxxx",
    )
    assert info.status == "ok"
    assert info.genres == []


def test_unparsed_page_is_counted_missing_and_not_cached(tmp_path, monkeypatch):
    import matchcut.enrich as enrich_module

    monkeypatch.setattr(
        enrich_module, "_get_with_backoff", lambda session, boxd_id: "<html></html>"
    )
    monkeypatch.setattr(enrich_module.time, "sleep", lambda s: None)
    cache = tmp_path / "films.json"
    refs = {"xxxx": FilmRef("xxxx", "Whatever", 2000)}

    films, missing = enrich_module.enrich(refs, cache)

    assert missing == 1
    assert films["xxxx"].status == "unparsed"
    assert load_cache(cache) == {}


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
