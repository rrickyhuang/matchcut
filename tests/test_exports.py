"""Export parsing, including the shapes real Letterboxd exports actually have."""

from __future__ import annotations

import zipfile

import pytest

from matchcut.exports import (
    ExportError,
    boxd_id_from_uri,
    load_people,
    load_person,
)

from .conftest import ANA_RATINGS, write_export


def test_label_comes_from_the_profile_username(exports_dir):
    """The export file name is `letterboxd-<user>-<date>-utc.zip`, which would
    make a terrible report label."""
    assert [p.label for p in load_people(exports_dir)] == ["ana", "ben"]


def test_label_falls_back_to_the_file_name_without_a_profile(tmp_path):
    path = write_export(tmp_path / "letterboxd-cleo-2026-03-04-05-06-utc.zip", "", {"aaa": 4.0})
    with zipfile.ZipFile(path) as archive:
        assert "profile.csv" in archive.namelist()
    # An empty Username falls through to the file-name pattern.
    assert load_person(path).label == "cleo"


def test_films_are_keyed_by_boxd_id_not_title(exports_dir):
    ana = load_people(exports_dir)[0]
    assert set(ana.ratings) == set(ANA_RATINGS)
    assert ana.ratings["eee"] == 5.0


def test_rated_films_count_as_watched(tmp_path):
    """watched.csv can lag behind ratings.csv."""
    path = write_export(
        tmp_path / "letterboxd-dee-2026-01-01-00-00-utc.zip",
        "dee",
        {"aaa": 4.0, "bbb": 3.0},
        watched={"aaa": "2024-01-01"},
    )
    person = load_person(path)
    assert set(person.watched) == {"aaa", "bbb"}


def test_watched_dates_are_kept_for_calling_cards(exports_dir):
    ana = load_people(exports_dir)[0]
    assert ana.watched_dates["eee"] == "2024-05-01"


def test_missing_watchlist_is_recorded_not_fatal(tmp_path):
    path = write_export(
        tmp_path / "letterboxd-eli-2026-01-01-00-00-utc.zip", "eli", {"aaa": 4.0}
    )
    person = load_person(path)
    assert person.has_watchlist is False
    assert person.watchlist == {}


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("https://boxd.it/zld0", "zld0"),
        ("http://boxd.it/4t3XBp", "4t3XBp"),
        ("https://letterboxd.com/film/challengers/", None),
        ("", None),
        (None, None),
    ],
)
def test_boxd_id_extraction(uri, expected):
    assert boxd_id_from_uri(uri) == expected


@pytest.mark.parametrize("rating", ["0", "5.5", "2.3", "", "n/a", "-1"])
def test_out_of_range_ratings_are_dropped(tmp_path, rating):
    """Letterboxd ratings are 0.5 to 5 in half-star steps; nothing else counts."""
    path = tmp_path / "letterboxd-fay-2026-01-01-00-00-utc.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ratings.csv",
            "Date,Name,Year,Letterboxd URI,Rating\n"
            f"2024-01-01,Alpha,1994,https://boxd.it/aaa,{rating}\n",
        )
    assert load_person(path).ratings == {}


def test_half_star_ratings_are_kept(tmp_path):
    path = tmp_path / "letterboxd-gus-2026-01-01-00-00-utc.zip"
    write_export(path, "gus", {"aaa": 0.5, "bbb": 4.5})
    assert load_person(path).ratings == {"aaa": 0.5, "bbb": 4.5}


def test_a_single_person_is_rejected(tmp_path):
    folder = tmp_path / "exports"
    folder.mkdir()
    write_export(folder / "letterboxd-ana-2026-01-01-00-00-utc.zip", "ana", {"aaa": 4.0})
    with pytest.raises(ExportError, match="at least 2"):
        load_people(folder)


def test_people_filter_is_case_insensitive(exports_dir):
    with pytest.raises(ExportError, match="at least 2"):
        load_people(exports_dir, only=["ANA"])
    assert [p.label for p in load_people(exports_dir, only=["ANA", "Ben"])] == [
        "ana",
        "ben",
    ]


def test_unknown_person_lists_what_is_available(exports_dir):
    with pytest.raises(ExportError, match="Available: ana, ben"):
        load_people(exports_dir, only=["ana", "nobody"])


def test_missing_folder_is_reported_clearly(tmp_path):
    with pytest.raises(ExportError, match="no such exports folder"):
        load_people(tmp_path / "nope")


def test_empty_folder_is_reported_clearly(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    with pytest.raises(ExportError, match="no export zips"):
        load_people(folder)


def test_two_exports_for_one_person_are_rejected(exports_dir):
    """A re-export left next to the old one would otherwise count as a third
    person called ana."""
    write_export(
        exports_dir / "letterboxd-ana-2026-03-01-00-00-utc.zip", "ana", {"aaa": 4.0}
    )
    with pytest.raises(ExportError) as caught:
        load_people(exports_dir)
    message = str(caught.value)
    assert "letterboxd-ana-2026-01-01-00-00-utc.zip" in message
    assert "letterboxd-ana-2026-03-01-00-00-utc.zip" in message
    assert "same person" in message


def test_duplicate_labels_are_compared_case_insensitively(exports_dir):
    write_export(exports_dir / "second.zip", "ANA", {"aaa": 4.0})
    with pytest.raises(ExportError, match="same person"):
        load_people(exports_dir)


def test_a_duplicate_outside_the_people_filter_is_not_an_error(exports_dir):
    """Only the selected people have to be unique."""
    write_export(exports_dir / "cleo-1.zip", "cleo", {"aaa": 4.0})
    write_export(exports_dir / "cleo-2.zip", "cleo", {"aaa": 4.0})
    assert [p.label for p in load_people(exports_dir, only=["ana", "ben"])] == [
        "ana",
        "ben",
    ]
    with pytest.raises(ExportError, match="same person"):
        load_people(exports_dir, only=["ana", "cleo"])

