"""Shared data types.

Every stage of the pipeline passes these around, so they are the contract
between `exports`, `enrich`, `metrics`, `recommend` and `render`.

Films are keyed by their `boxd.it` short id everywhere, never by title.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# A Letterboxd rating: 0.5 to 5.0 in half-star steps.
RATING_STEPS: tuple[float, ...] = tuple(i / 2 for i in range(1, 11))


@dataclass(frozen=True)
class FilmRef:
    """A film as it appears in an export, before enrichment."""

    boxd_id: str
    title: str
    year: int | None


@dataclass
class FilmInfo:
    """An enriched film record, as cached in `cache/films.json`.

    `status` is "ok" when the page parsed, otherwise a short failure tag.
    Only `status == "ok"` records count toward genre, decade and language
    sections; the rest are counted and reported as missing.
    """

    boxd_id: str
    title: str
    year: int | None
    slug: str | None = None
    genres: list[str] = field(default_factory=list)
    primary_language: str | None = None
    spoken_languages: list[str] = field(default_factory=list)
    tmdb_id: str | None = None
    status: str = "ok"
    fetched_at: str | None = None

    @property
    def decade(self) -> int | None:
        return (self.year // 10) * 10 if self.year is not None else None


@dataclass
class Person:
    """One person's export, keyed by the zip file name without `.zip`."""

    label: str
    ratings: dict[str, float] = field(default_factory=dict)
    watched: dict[str, FilmRef] = field(default_factory=dict)
    watchlist: dict[str, FilmRef] = field(default_factory=dict)
    has_watchlist: bool = False

    @property
    def rated_ids(self) -> set[str]:
        return set(self.ratings)

    @property
    def watched_ids(self) -> set[str]:
        return set(self.watched)


@dataclass
class Group:
    """Everyone in the report, plus the enrichment they share."""

    people: list[Person]
    films: dict[str, FilmInfo] = field(default_factory=dict)

    @property
    def labels(self) -> list[str]:
        return [p.label for p in self.people]

    def enriched(self, boxd_id: str) -> FilmInfo | None:
        """The film's record, or None when it is missing or failed to parse."""
        info = self.films.get(boxd_id)
        return info if info is not None and info.status == "ok" else None


@dataclass
class Thresholds:
    """Sample-size floors, all overridable from the command line."""

    min_overlap: int = 30
    min_group: int = 8
