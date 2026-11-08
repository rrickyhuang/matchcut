"""Made-up exports, small enough that every answer can be worked out by hand.

The ratings below are chosen so the expected numbers are exact, not
approximate -- see `tests/test_metrics.py` for the arithmetic each one checks.

Nothing here comes from a real export.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest

from matchcut.models import FilmInfo, Group, Thresholds

# boxd_id -> (title, year, genres, primary language)
FILMS = {
    "aaa": ("Alpha", 1994, ["Drama"], "English"),
    "bbb": ("Bravo", 2004, ["Drama", "Comedy"], "English"),
    "ccc": ("Charlie", 2014, ["Comedy"], "English"),
    "ddd": ("Delta", 2024, ["Horror"], "Korean"),
    "eee": ("Echo", 2024, ["Horror"], "Korean"),
    "fff": ("Foxtrot", 1974, ["Drama"], "French"),
}

#: Ana and Ben share aaa..ddd. Their ratings move together exactly, two stars
#: apart on every film, which makes the correlation exactly 1.0 and the mean
#: absolute difference exactly 2.0.
ANA_RATINGS = {"aaa": 1.0, "bbb": 2.0, "ccc": 3.0, "ddd": 4.0, "eee": 5.0}
BEN_RATINGS = {"aaa": 3.0, "bbb": 4.0, "ccc": 5.0, "ddd": 2.0}

#: Cleo rates everything 3, so her variance is zero and no correlation exists.
CLEO_RATINGS = {"aaa": 3.0, "bbb": 3.0, "ccc": 3.0}


def _csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def write_export(
    path: Path,
    username: str,
    ratings: dict[str, float],
    watched: dict[str, str] | None = None,
    watchlist: list[str] | None = None,
) -> Path:
    """Write one export zip. `watched` maps boxd_id -> logged date."""
    watched = watched if watched is not None else {i: "2024-01-01" for i in ratings}

    def film_row(boxd_id: str, date: str) -> list[str]:
        title, year, _, _ = FILMS[boxd_id]
        return [date, title, str(year), f"https://boxd.it/{boxd_id}"]

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "profile.csv",
            _csv_bytes(
                ["Date Joined", "Username", "Given Name"],
                [["2023-01-01", username, ""]],
            ),
        )
        archive.writestr(
            "ratings.csv",
            _csv_bytes(
                ["Date", "Name", "Year", "Letterboxd URI", "Rating"],
                [
                    film_row(i, watched.get(i, "2024-01-01")) + [f"{r:g}"]
                    for i, r in ratings.items()
                ],
            ),
        )
        archive.writestr(
            "watched.csv",
            _csv_bytes(
                ["Date", "Name", "Year", "Letterboxd URI"],
                [film_row(i, d) for i, d in watched.items()],
            ),
        )
        if watchlist is not None:
            archive.writestr(
                "watchlist.csv",
                _csv_bytes(
                    ["Date", "Name", "Year", "Letterboxd URI"],
                    [film_row(i, "2024-06-01") for i in watchlist],
                ),
            )
    return path


@pytest.fixture
def exports_dir(tmp_path: Path) -> Path:
    """Two people: Ana and Ben. Ana has an extra film and a watchlist."""
    folder = tmp_path / "exports"
    folder.mkdir()
    write_export(
        folder / "letterboxd-ana-2026-01-01-00-00-utc.zip",
        "ana",
        ANA_RATINGS,
        watched={
            "aaa": "2024-01-01",
            "bbb": "2024-02-01",
            "ccc": "2024-03-01",
            "ddd": "2024-04-01",
            "eee": "2024-05-01",
        },
        watchlist=["fff"],
    )
    write_export(
        folder / "letterboxd-ben-2026-01-01-00-00-utc.zip",
        "ben",
        BEN_RATINGS,
        watchlist=["fff"],
    )
    return folder


@pytest.fixture
def films() -> dict[str, FilmInfo]:
    return {
        boxd_id: FilmInfo(
            boxd_id=boxd_id,
            title=title,
            year=year,
            genres=list(genres),
            primary_language=language,
            status="ok",
        )
        for boxd_id, (title, year, genres, language) in FILMS.items()
    }


@pytest.fixture
def group(exports_dir: Path, films) -> Group:
    from matchcut.exports import load_people

    return Group(people=load_people(exports_dir), films=films)


@pytest.fixture
def thresholds() -> Thresholds:
    """Floors low enough that the fixtures clear them, so tests check the
    arithmetic rather than the sample-size gates. Gate behaviour has its own
    tests that pass the defaults explicitly."""
    return Thresholds(min_overlap=3, min_group=2)
