"""Read Letterboxd export zips into `Person` records.

One zip per person. Column names below are confirmed against real exports
(Nov 2026): the files are UTF-8 with no BOM, and titles can carry en dashes and
non-breaking spaces, so nothing here re-encodes a title.

Read from each zip:
  profile.csv    Date Joined, Username, Given Name, ...   (label only)
  ratings.csv    Date, Name, Year, Letterboxd URI, Rating
  watched.csv    Date, Name, Year, Letterboxd URI
  watchlist.csv  Date, Name, Year, Letterboxd URI         (optional)

Column lookup is confined to the constants below and `_row_to_ref`, so a change
in the export format has one place to fix.

Only ratings matter for similarity; unrated watched films are ignored there.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from .models import FilmRef, Person

URI_COLUMN = "Letterboxd URI"
NAME_COLUMN = "Name"
YEAR_COLUMN = "Year"
DATE_COLUMN = "Date"
RATING_COLUMN = "Rating"
USERNAME_COLUMN = "Username"

MIN_PEOPLE = 2
#: Beyond this the pair table and the correlation matrix stop being readable.
MAX_PEOPLE = 6

#: `https://boxd.it/<id>` -- the short link every export row carries.
_BOXD_RE = re.compile(r"boxd\.it/([A-Za-z0-9]+)")

#: Letterboxd names its exports `letterboxd-<username>-<date>-utc.zip`.
_EXPORT_NAME_RE = re.compile(
    r"^letterboxd-(?P<user>.+?)-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-utc$", re.IGNORECASE
)


class ExportError(Exception):
    """An export zip could not be used."""


def load_people(exports_dir: Path, only: list[str] | None = None) -> list[Person]:
    """Load every `*.zip` in `exports_dir`, optionally limited to `only` labels.

    Labels are matched case-insensitively. Raises `ExportError` if the folder is
    missing, if a requested label has no zip, or if the group is the wrong size.
    """
    if not exports_dir.is_dir():
        raise ExportError(f"no such exports folder: {exports_dir}")

    zips = sorted(exports_dir.glob("*.zip"))
    if not zips:
        raise ExportError(f"no export zips in {exports_dir}")

    loaded = [(path, load_person(path)) for path in zips]
    people = [person for _, person in loaded]

    if only:
        wanted = {label.casefold() for label in only}
        found = {p.label.casefold() for p in people}
        missing = wanted - found
        if missing:
            available = ", ".join(sorted(p.label for p in people))
            raise ExportError(
                f"no export for {', '.join(sorted(missing))}. Available: {available}"
            )
        loaded = [(path, p) for path, p in loaded if p.label.casefold() in wanted]
        people = [person for _, person in loaded]

    _reject_duplicate_labels(loaded)

    if len(people) < MIN_PEOPLE:
        raise ExportError(f"need at least {MIN_PEOPLE} people, got {len(people)}")
    if len(people) > MAX_PEOPLE:
        raise ExportError(
            f"{len(people)} people; the pair table and matrix only stay readable "
            f"up to {MAX_PEOPLE}. Use --people to pick a subset."
        )
    return people


def _reject_duplicate_labels(loaded: list[tuple[Path, Person]]) -> None:
    """Two zips with one label would be counted as two people.

    Everything downstream is keyed by label, so a second export of the same
    account (a re-export left beside the old one) would be silently merged or
    ignored. Make the user choose which file to keep.
    """
    by_label: dict[str, list[str]] = {}
    for path, person in loaded:
        by_label.setdefault(person.label.casefold(), []).append(path.name)
    for names in by_label.values():
        if len(names) > 1:
            raise ExportError(
                f"{' and '.join(names)} are exports for the same person. "
                "Keep one of them in the folder."
            )


def load_person(zip_path: Path) -> Person:
    """Read one export zip into a `Person`."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ExportError(f"{zip_path.name}: not a readable zip ({exc})") from exc

    with archive:
        names = set(archive.namelist())
        label = _label_for(archive, names, zip_path)

        if "ratings.csv" not in names:
            raise ExportError(f"{zip_path.name}: no ratings.csv")

        ratings: dict[str, float] = {}
        rated_refs: dict[str, FilmRef] = {}
        for row in _checked_rows(
            archive, "ratings.csv", zip_path, (URI_COLUMN, RATING_COLUMN)
        ):
            ref = _row_to_ref(row)
            rating = _parse_rating(row.get(RATING_COLUMN))
            if ref is None or rating is None:
                continue
            ratings[ref.boxd_id] = rating
            rated_refs[ref.boxd_id] = ref

        watched: dict[str, FilmRef] = {}
        watched_dates: dict[str, str] = {}
        if "watched.csv" in names:
            for row in _checked_rows(archive, "watched.csv", zip_path, (URI_COLUMN,)):
                ref = _row_to_ref(row)
                if ref is None:
                    continue
                watched[ref.boxd_id] = ref
                watched_dates[ref.boxd_id] = (row.get(DATE_COLUMN) or "").strip()

        # A rated film is watched by definition, even if watched.csv lags.
        for boxd_id, ref in rated_refs.items():
            watched.setdefault(boxd_id, ref)

        has_watchlist = "watchlist.csv" in names
        watchlist: dict[str, FilmRef] = {}
        if has_watchlist:
            for row in _checked_rows(
                archive, "watchlist.csv", zip_path, (URI_COLUMN,)
            ):
                ref = _row_to_ref(row)
                if ref is not None:
                    watchlist[ref.boxd_id] = ref

    return Person(
        label=label,
        ratings=ratings,
        watched=watched,
        watchlist=watchlist,
        has_watchlist=has_watchlist,
        watched_dates=watched_dates,
    )


def _label_for(archive: zipfile.ZipFile, names: set[str], zip_path: Path) -> str:
    """Prefer the Letterboxd username, then the export file name, then the stem.

    Letterboxd names exports `letterboxd-<user>-<date>-utc.zip`, so the raw
    stem makes a terrible report label.
    """
    if "profile.csv" in names:
        for row in _rows(archive, "profile.csv"):
            username = (row.get(USERNAME_COLUMN) or "").strip()
            if username:
                return username
            break

    match = _EXPORT_NAME_RE.match(zip_path.stem)
    if match:
        return match.group("user")
    return zip_path.stem


def _reader(archive: zipfile.ZipFile, member: str) -> csv.DictReader:
    """A DictReader over a member CSV. Exports are UTF-8; tolerate a BOM.

    The one place a member is decoded, so every file is read the same way.
    """
    raw = archive.read(member).decode("utf-8-sig", errors="replace")
    return csv.DictReader(io.StringIO(raw))


def _rows(archive: zipfile.ZipFile, member: str):
    """Yield dict rows from a member CSV."""
    yield from _reader(archive, member)


def _checked_rows(
    archive: zipfile.ZipFile,
    member: str,
    zip_path: Path,
    required: tuple[str, ...],
) -> list[dict[str, str]]:
    """Rows of a member CSV, failing loudly when its format has changed.

    Rows that cannot be used are skipped by the caller, which would turn a
    renamed column or a new link format into a person with no films and no
    error. So: a header missing a required column is an error, and so is a
    file that has rows but not one `boxd.it` link. An empty file, or a header
    with no rows, is fine.
    """
    reader = _reader(archive, member)
    if reader.fieldnames is None:
        return []
    absent = [column for column in required if column not in reader.fieldnames]
    if absent:
        raise ExportError(
            f"{zip_path.name}: {member} has no {', '.join(absent)} column "
            f"(found: {', '.join(reader.fieldnames)}). Has the export format changed?"
        )
    rows = list(reader)
    if rows and not any(boxd_id_from_uri(row.get(URI_COLUMN)) for row in rows):
        raise ExportError(
            f"{zip_path.name}: none of the {len(rows)} rows in {member} has a "
            f"boxd.it link in {URI_COLUMN!r}. Has the export format changed?"
        )
    return rows


def boxd_id_from_uri(uri: str | None) -> str | None:
    """Pull the short id out of a `boxd.it` URI, or None if it is not one."""
    if not uri:
        return None
    match = _BOXD_RE.search(uri)
    return match.group(1) if match else None


def _parse_rating(value: str | None) -> float | None:
    """Ratings run 0.5 to 5 in half-star steps. Anything else is dropped."""
    if not value:
        return None
    try:
        rating = float(value)
    except ValueError:
        return None
    if not (0.5 <= rating <= 5.0) or (rating * 2) % 1 != 0:
        return None
    return rating


def _row_to_ref(row: dict[str, str]) -> FilmRef | None:
    """Turn one CSV row into a `FilmRef`, or None when the URI is unusable."""
    boxd_id = boxd_id_from_uri(row.get(URI_COLUMN))
    if boxd_id is None:
        return None
    year_raw = (row.get(YEAR_COLUMN) or "").strip()
    year = int(year_raw) if year_raw.isdigit() else None
    return FilmRef(
        boxd_id=boxd_id,
        title=(row.get(NAME_COLUMN) or "").strip() or boxd_id,
        year=year,
    )
