"""The fetching rules in `enrich`: throttle, backoff, block streak and resume.

No network is touched. `requests.Session` is replaced by a scripted fake and
`time` is patched, so the rules are checked by counting calls and recorded
sleeps rather than by waiting.
"""

from __future__ import annotations

import itertools

import pytest
import requests

import matchcut.enrich as enrich_module
from matchcut.enrich import BLOCK_STREAK, MAX_RETRIES, enrich, load_cache, save_cache
from matchcut.models import FilmInfo, FilmRef

PAGE = (
    '<html><body><h1 class="primaryname">Some Film</h1>'
    '<div id="tab-panel-details"></div></body></html>'
)


class FakeResponse:
    def __init__(self, status_code: int, text: str = PAGE):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Plays back one scripted outcome per request: a response or an error."""

    def __init__(self, script):
        self.script = list(script)
        self.urls: list[str] = []
        self.headers: dict = {}

    def get(self, url, timeout=None, allow_redirects=True):
        self.urls.append(url)
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """Record sleeps instead of waiting. The clock jumps 100s per reading, so
    the one-request-per-second throttle never fires unless a test wants it."""
    recorded: list[float] = []
    ticks = itertools.count(start=100, step=100)
    monkeypatch.setattr(enrich_module.time, "sleep", recorded.append)
    monkeypatch.setattr(enrich_module.time, "monotonic", lambda: float(next(ticks)))
    return recorded


def install(monkeypatch, script) -> FakeSession:
    session = FakeSession(script)
    monkeypatch.setattr(enrich_module.requests, "Session", lambda: session)
    return session


def refs_for(*ids: str) -> dict[str, FilmRef]:
    return {i: FilmRef(i, f"Film {i}", 2000) for i in ids}


def ids(n: int) -> list[str]:
    return [f"f{i:02d}" for i in range(n)]


# --------------------------------------------------------------------------
# block streak
# --------------------------------------------------------------------------


def test_stops_after_five_consecutive_refusals(monkeypatch, sleeps, tmp_path):
    session = install(monkeypatch, [FakeResponse(429)] * 20)
    refs = refs_for(*ids(8))

    films, missing = enrich(refs, tmp_path / "films.json")

    assert len(session.urls) == BLOCK_STREAK == 5
    assert missing == 8
    assert all(info.status == "missing" for info in films.values())


def test_403_counts_toward_the_streak_like_429(monkeypatch, sleeps, tmp_path):
    session = install(monkeypatch, [FakeResponse(403)] * 20)
    enrich(refs_for(*ids(8)), tmp_path / "films.json")
    assert len(session.urls) == BLOCK_STREAK


CHALLENGE = FakeResponse(200, "<html><body><p>Just a moment...</p></body></html>")
FILM = FakeResponse(200)


def test_challenge_pages_served_as_200_stop_the_run(monkeypatch, sleeps, tmp_path):
    """A block that answers 200 with a challenge page is still a block."""
    session = install(monkeypatch, [CHALLENGE] * 20)

    films, missing = enrich(refs_for(*ids(12)), tmp_path / "films.json")

    assert len(session.urls) == BLOCK_STREAK
    assert missing == 12
    assert all(info.status != "ok" for info in films.values())


def test_a_real_film_page_resets_the_challenge_streak(monkeypatch, sleeps, tmp_path):
    script = [CHALLENGE] * 4 + [FILM] + [CHALLENGE] * 4 + [FILM]
    session = install(monkeypatch, script)

    enrich(refs_for(*ids(10)), tmp_path / "films.json")

    assert len(session.urls) == 10


def test_refusals_and_challenge_pages_count_together(monkeypatch, sleeps, tmp_path):
    script = [FakeResponse(429)] * 3 + [CHALLENGE] * 2 + [FILM] * 5
    session = install(monkeypatch, script)

    enrich(refs_for(*ids(10)), tmp_path / "films.json")

    assert len(session.urls) == BLOCK_STREAK


def test_a_success_resets_the_streak(monkeypatch, sleeps, tmp_path):
    """Four refusals, a success, four more: never five in a row, so every
    film is requested."""
    script = (
        [FakeResponse(429)] * 4
        + [FakeResponse(200)]
        + [FakeResponse(429)] * 4
        + [FakeResponse(200)]
    )
    session = install(monkeypatch, script)

    films, missing = enrich(refs_for(*ids(10)), tmp_path / "films.json")

    assert len(session.urls) == 10
    assert missing == 8  # only the two successes are ok
    assert sum(1 for i in films.values() if i.status == "ok") == 2


def test_a_network_error_resets_the_streak(monkeypatch, sleeps, tmp_path):
    boom = requests.ConnectionError("down")
    script = [FakeResponse(429)] * 4 + [boom] * MAX_RETRIES + [FakeResponse(429)] * 4
    session = install(monkeypatch, script)

    enrich(refs_for(*ids(9)), tmp_path / "films.json")

    # 4 refusals + 4 retries of the failing film + 4 refusals = every film tried.
    assert len(session.urls) == 4 + MAX_RETRIES + 4


# --------------------------------------------------------------------------
# resume and refresh
# --------------------------------------------------------------------------


def cached_film(boxd_id: str) -> FilmInfo:
    return FilmInfo(boxd_id=boxd_id, title="Cached", year=1999, genres=["Drama"])


def test_cached_ok_films_are_never_requested(monkeypatch, sleeps, tmp_path):
    path = tmp_path / "films.json"
    save_cache(path, {"aaa": cached_film("aaa")})
    session = install(monkeypatch, [])

    films, missing = enrich(refs_for("aaa"), path)

    assert session.urls == []
    assert missing == 0
    assert films["aaa"].title == "Cached"


def test_only_the_uncached_films_are_requested(monkeypatch, sleeps, tmp_path):
    path = tmp_path / "films.json"
    save_cache(path, {"aaa": cached_film("aaa")})
    session = install(monkeypatch, [FakeResponse(200)])

    films, missing = enrich(refs_for("aaa", "bbb"), path)

    assert session.urls == ["https://boxd.it/bbb"]
    assert missing == 0
    assert set(films) == {"aaa", "bbb"}


def test_refresh_requests_cached_films_again(monkeypatch, sleeps, tmp_path):
    path = tmp_path / "films.json"
    save_cache(path, {"aaa": cached_film("aaa")})
    session = install(monkeypatch, [FakeResponse(200)])

    films, _ = enrich(refs_for("aaa"), path, refresh=True)

    assert session.urls == ["https://boxd.it/aaa"]
    assert films["aaa"].title == "Some Film"


def test_fetched_films_are_written_to_the_cache(monkeypatch, sleeps, tmp_path):
    path = tmp_path / "films.json"
    install(monkeypatch, [FakeResponse(200)])

    enrich(refs_for("aaa"), path)

    assert set(load_cache(path)) == {"aaa"}


# --------------------------------------------------------------------------
# backoff and failure records
# --------------------------------------------------------------------------


def test_server_errors_back_off_exponentially_then_succeed(monkeypatch, sleeps, tmp_path):
    install(monkeypatch, [FakeResponse(500), FakeResponse(503), FakeResponse(200)])

    films, missing = enrich(refs_for("aaa"), tmp_path / "films.json")

    assert sleeps == [1.0, 2.0]
    assert missing == 0
    assert films["aaa"].status == "ok"


def test_gives_up_after_max_retries_and_records_the_error(monkeypatch, sleeps, tmp_path):
    install(monkeypatch, [requests.ConnectionError("down")] * MAX_RETRIES)
    path = tmp_path / "films.json"

    films, missing = enrich(refs_for("aaa"), path)

    assert sleeps == [1.0, 2.0, 4.0, 8.0]
    assert missing == 1
    assert films["aaa"].status == "error: ConnectionError"
    assert load_cache(path) == {}  # a failure is retried next run


def test_other_client_errors_are_recorded_not_fatal(monkeypatch, sleeps, tmp_path):
    session = install(monkeypatch, [FakeResponse(404), FakeResponse(200)])

    films, missing = enrich(refs_for("aaa", "bbb"), tmp_path / "films.json")

    assert len(session.urls) == 2
    assert films["aaa"].status == "error: HTTPError"
    assert films["bbb"].status == "ok"
    assert missing == 1


# --------------------------------------------------------------------------
# throttle
# --------------------------------------------------------------------------


def test_requests_are_spaced_one_second_apart(monkeypatch, tmp_path):
    recorded: list[float] = []
    monkeypatch.setattr(enrich_module.time, "sleep", recorded.append)
    monkeypatch.setattr(enrich_module.time, "monotonic", lambda: 100.0)
    install(monkeypatch, [FakeResponse(200), FakeResponse(200)])

    enrich(refs_for("aaa", "bbb"), tmp_path / "films.json")

    # The clock never advances, so the second request has to wait the full
    # interval; the first has no earlier request to wait for.
    assert recorded == [enrich_module.REQUEST_INTERVAL_SECONDS]
