"""Fetch and cache genre, language and TMDB id from Letterboxd film pages.

The export carries no genre or language, so each unique film across all people
is looked up once by following its `boxd.it` link to the film page.

Fetching rules (from the spec, all enforced here):
  - One request per second, browser-like user agent.
  - Exponential backoff on network errors.
  - Resume from the cache; never re-fetch a film whose status is "ok".
  - After `BLOCK_STREAK` consecutive 403/429 responses, stop and build a
    partial report.

Page parsing lives only in `parse_film_page` so the one brittle part of the
project has a single test against a saved page, never the live site.
"""

from __future__ import annotations

from pathlib import Path

from .models import FilmInfo, FilmRef

REQUEST_INTERVAL_SECONDS = 1.0
BLOCK_STREAK = 5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class Blocked(Exception):
    """Raised when Letterboxd has refused `BLOCK_STREAK` requests in a row."""


def enrich(
    refs: dict[str, FilmRef],
    cache_path: Path,
    refresh: bool = False,
) -> tuple[dict[str, FilmInfo], int]:
    """Return every film's info plus the count that still lacks genre/language.

    Writes the cache as it goes so an interrupted run resumes where it stopped.
    A non-zero second value means the report must declare itself partial.
    """
    raise NotImplementedError


def load_cache(cache_path: Path) -> dict[str, FilmInfo]:
    """Read `cache/films.json`, returning an empty dict when it is absent."""
    raise NotImplementedError


def save_cache(cache_path: Path, films: dict[str, FilmInfo]) -> None:
    """Write the cache atomically, so an interrupt cannot truncate it."""
    raise NotImplementedError


def fetch_film_page(boxd_id: str) -> str:
    """Follow `https://boxd.it/<id>` and return the film page HTML."""
    raise NotImplementedError


def parse_film_page(html: str, boxd_id: str) -> FilmInfo:
    """Pull title, year, slug, genres, languages and TMDB id out of a page.

    The only function that knows the page's structure. Tested against
    `tests/fixtures/film_page.html`.
    """
    raise NotImplementedError
