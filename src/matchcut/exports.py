"""Read Letterboxd export zips into `Person` records.

One zip per person. The file name without `.zip` becomes the person's label.

Read from each zip:
  ratings.csv    date, name, year, Letterboxd URI, rating
  watched.csv    date, name, year, Letterboxd URI
  watchlist.csv  date, name, year, Letterboxd URI  (optional)

The column names above come from the documented standard export. Confirm them
against a real export before trusting this parser, and keep the column lookup
in `_row_to_ref` so there is one place to fix.

Only ratings matter for similarity; unrated watched films are ignored there.
"""

from __future__ import annotations

from pathlib import Path

from .models import FilmRef, Person

#: Column that holds the `https://boxd.it/<id>` short link.
URI_COLUMN = "Letterboxd URI"


def load_people(exports_dir: Path, only: list[str] | None = None) -> list[Person]:
    """Load every `*.zip` in `exports_dir`, optionally limited to `only` labels.

    Raises if a requested label has no zip, or if fewer than 2 people load.
    """
    raise NotImplementedError


def load_person(zip_path: Path) -> Person:
    """Read one export zip."""
    raise NotImplementedError


def boxd_id_from_uri(uri: str) -> str | None:
    """Pull the short id out of a `boxd.it` URI, or None if it is not one."""
    raise NotImplementedError


def _row_to_ref(row: dict[str, str]) -> FilmRef | None:
    """Turn one CSV row into a `FilmRef`, or None when the URI is unusable."""
    raise NotImplementedError
