"""Fetch and cache genre, language and TMDB id from Letterboxd film pages.

The export carries no genre or language, so each unique *watched* film is
looked up once by following its `boxd.it` link to the public film page.
Watchlist-only films are never fetched: the watchlist list needs nothing but
the title and year the export already gives.

Confirmed against live pages (Nov 2026): a plain `requests` session with
browser-like headers is served normally, and everything needed is in the single
film page -- no second request for a details tab.

Fetching rules, all enforced here:
  - One request per second, browser-like user agent.
  - Exponential backoff on network errors.
  - Resume from the cache; never re-fetch a film whose status is "ok".
  - After `BLOCK_STREAK` consecutive 403/429 responses, stop and build a
    partial report.

Page parsing lives only in `parse_film_page`, so the one brittle part of the
project has a single test against a saved page, never the live site.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .models import FilmInfo, FilmRef

REQUEST_INTERVAL_SECONDS = 1.0
BLOCK_STREAK = 5
MAX_RETRIES = 4
TIMEOUT_SECONDS = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

#: Headings in the film page's details panel, which is where languages live.
PRIMARY_LANGUAGE_HEADINGS = ("primary language", "language")

#: Flush the cache this often, so an interrupted run loses almost nothing.
SAVE_EVERY = 25


class Blocked(Exception):
    """Letterboxd refused a request with 403 or 429."""


def enrich(
    refs: dict[str, FilmRef],
    cache_path: Path,
    refresh: bool = False,
    progress=None,
) -> tuple[dict[str, FilmInfo], int]:
    """Return every film's info plus the count that still lacks genre/language.

    A non-zero second value means the report must declare itself partial.
    """
    cached = {} if refresh else load_cache(cache_path)
    films: dict[str, FilmInfo] = {
        boxd_id: info
        for boxd_id, info in cached.items()
        if boxd_id in refs and info.status == "ok"
    }

    todo = [boxd_id for boxd_id in refs if boxd_id not in films]
    if progress:
        progress(
            f"{len(films)} films cached, {len(todo)} to fetch "
            f"(about {len(todo) * REQUEST_INTERVAL_SECONDS / 60:.0f} min)"
        )
    if todo:
        _fetch_all(todo, refs, films, cache_path, progress)

    # Films never fetched, or whose fetch failed, still need a record so the
    # report can count them and leave them out of the right sections.
    for boxd_id, ref in refs.items():
        if boxd_id not in films:
            films[boxd_id] = FilmInfo(
                boxd_id=boxd_id, title=ref.title, year=ref.year, status="missing"
            )

    missing = sum(1 for info in films.values() if info.status != "ok")
    return films, missing


def _fetch_all(
    todo: list[str],
    refs: dict[str, FilmRef],
    films: dict[str, FilmInfo],
    cache_path: Path,
    progress=None,
) -> None:
    """Fetch each id in `todo`, stopping early if Letterboxd starts refusing."""
    session = requests.Session()
    session.headers.update(HEADERS)
    refused_streak = 0
    last_request = 0.0
    fetched = 0

    # The `finally` is what makes "an interrupted run resumes from the cache"
    # true: Ctrl-C or an unexpected error still saves what was fetched.
    try:
        for index, boxd_id in enumerate(todo, start=1):
            wait = REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_request)
            if wait > 0:
                time.sleep(wait)
            last_request = time.monotonic()

            try:
                html = _get_with_backoff(session, boxd_id)
            except Blocked:
                refused_streak += 1
                if refused_streak >= BLOCK_STREAK:
                    if progress:
                        progress(
                            f"  Letterboxd refused {BLOCK_STREAK} requests in a "
                            f"row; stopping after {index - 1} of {len(todo)}"
                        )
                    break
                continue
            except requests.RequestException as exc:
                films[boxd_id] = FilmInfo(
                    boxd_id=boxd_id,
                    title=refs[boxd_id].title,
                    year=refs[boxd_id].year,
                    status=f"error: {type(exc).__name__}",
                )
                refused_streak = 0
                continue

            refused_streak = 0
            films[boxd_id] = parse_film_page(html, boxd_id, fallback=refs[boxd_id])
            fetched += 1

            # Counted in films fetched, not position in `todo`, so refusals and
            # errors in between do not push a save off its cadence.
            if fetched % SAVE_EVERY == 0 or index == len(todo):
                save_cache(cache_path, films)
                if progress:
                    progress(f"  enriched {index}/{len(todo)}")
    finally:
        save_cache(cache_path, films)


def _get_with_backoff(session: requests.Session, boxd_id: str) -> str:
    """Fetch one film page, retrying network errors with exponential backoff.

    Raises `Blocked` on 403/429 so the caller can count consecutive refusals.
    """
    delay = 1.0
    last_exc: Exception | None = None
    for _ in range(MAX_RETRIES):
        try:
            response = session.get(
                f"https://boxd.it/{boxd_id}",
                timeout=TIMEOUT_SECONDS,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(delay)
            delay *= 2
            continue

        if response.status_code in (403, 429):
            raise Blocked(f"{boxd_id}: HTTP {response.status_code}")
        if response.status_code >= 500:
            last_exc = requests.HTTPError(f"HTTP {response.status_code}")
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()
        return response.text

    raise last_exc or requests.RequestException(f"{boxd_id}: gave up")


# --------------------------------------------------------------------------
# Parsing. The only code that knows the film page's structure.
# --------------------------------------------------------------------------


def parse_film_page(
    html: str, boxd_id: str, fallback: FilmRef | None = None
) -> FilmInfo:
    """Pull title, year, genres, primary language and TMDB id out of a page.

    Tested against `tests/fixtures/film_page.html`, never the live site.

    A page showing none of the film page's own structure (a consent or
    bot-challenge page, or a layout change) comes back with status
    "unparsed", so it is counted as missing and never cached as if it were a
    film with no genres.
    """
    soup = BeautifulSoup(html, "html.parser")
    recognised = bool(
        soup.select_one("h1.primaryname")
        or soup.find(id="tab-panel-genres")
        or soup.find(id="tab-panel-details")
    )

    body = soup.find("body")
    tmdb_id = body.get("data-tmdb-id") if body else None

    title, year = _parse_title_year(soup)
    if fallback is not None:
        title = title or fallback.title
        year = year if year is not None else fallback.year

    genres = _slug_list(soup, "tab-panel-genres", "Genres", "/films/genre/")
    primary = _primary_language(soup)

    return FilmInfo(
        boxd_id=boxd_id,
        title=title or boxd_id,
        year=year,
        genres=genres,
        primary_language=primary,
        tmdb_id=str(tmdb_id) if tmdb_id else None,
        status="ok" if recognised else "unparsed",
        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


#: `Challengers (2024)` -> `Challengers`, for the og:title fallback.
_OG_TITLE_YEAR_RE = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")


def _parse_title_year(soup: BeautifulSoup) -> tuple[str | None, int | None]:
    """Read the film's own title and release year off the page header.

    The film title is `h1.primaryname`. The page's *first* `<h1>` is the site
    logo, so it must not be used.
    """
    node = soup.select_one("h1.primaryname")
    title = node.get_text(" ", strip=True) if node else None
    if not title:
        meta = soup.find("meta", attrs={"property": "og:title"})
        content = meta.get("content") if meta else None
        if content:
            title = _OG_TITLE_YEAR_RE.sub("", content).strip()

    year = None
    year_link = soup.find("a", href=lambda h: bool(h) and "/films/year/" in h)
    if year_link is not None:
        digits = "".join(ch for ch in year_link.get_text() if ch.isdigit())
        if len(digits) == 4:
            year = int(digits)
    return (title or None), year


def _panel_section(soup: BeautifulSoup, panel_id: str, heading: str):
    """The `.text-sluglist` that follows a given `<h3>` inside a given panel.

    Genres and Themes share a panel under different headings, and Primary and
    Spoken Languages share one too, so the heading has to be matched rather
    than taking the panel's first list.
    """
    panel = soup.find(id=panel_id)
    if panel is None:
        return None
    wanted = heading.casefold()
    for h3 in panel.find_all("h3"):
        if h3.get_text(" ", strip=True).casefold() == wanted:
            return h3.find_next_sibling(
                lambda tag: tag.name == "div"
                and "text-sluglist" in (tag.get("class") or [])
            )
    return None


def _slug_list(
    soup: BeautifulSoup, panel_id: str, heading: str, href_contains: str
) -> list[str]:
    """Link texts under one heading, de-duplicated, in page order."""
    section = _panel_section(soup, panel_id, heading)
    if section is None:
        return []
    found: list[str] = []
    for anchor in section.find_all("a", href=True):
        if href_contains not in anchor["href"]:
            continue
        text = anchor.get_text(" ", strip=True)
        if text and text not in found:
            found.append(text)
    return found


def _language_list(soup: BeautifulSoup, headings: tuple[str, ...]) -> list[str]:
    for heading in headings:
        found = _slug_list(soup, "tab-panel-details", heading, "/films/language/")
        if found:
            return found
    return []


def _primary_language(soup: BeautifulSoup) -> str | None:
    """The primary language. A film counts under this one only.

    Single-language films show only a `Language` heading, so that is the
    fallback -- but `Spoken Languages` is never read here, or a film would be
    counted under a language it merely contains.
    """
    found = _language_list(soup, PRIMARY_LANGUAGE_HEADINGS)
    return found[0] if found else None


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def load_cache(cache_path: Path) -> dict[str, FilmInfo]:
    """Read the cache, returning an empty dict when it is absent or unreadable."""
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    known = {f.name for f in fields(FilmInfo)}
    films: dict[str, FilmInfo] = {}
    for boxd_id, record in (raw.get("films") or {}).items():
        try:
            # Drop fields this version no longer has (older caches carry `slug`
            # and `spoken_languages`), so an existing cache keeps working.
            films[boxd_id] = FilmInfo(**{k: v for k, v in record.items() if k in known})
        except (TypeError, AttributeError):
            continue
    return films


def save_cache(cache_path: Path, films: dict[str, FilmInfo]) -> None:
    """Merge `films` into the cache on disk, writing atomically.

    Only `ok` records are stored: a failure is worth retrying next run. Films
    already on disk that are not in `films` are kept, so a run over a smaller
    or different group, or a `--refresh-cache` run that is blocked part-way,
    never shrinks the cache. A new `ok` record replaces the stored one.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    merged = load_cache(cache_path)
    merged.update({i: info for i, info in films.items() if info.status == "ok"})
    payload = {
        "version": 1,
        "films": {
            boxd_id: asdict(info) for boxd_id, info in sorted(merged.items())
        },
    }
    temp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    temp.replace(cache_path)
