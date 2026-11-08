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
        if isinstance(outcome, BaseException):  # includes KeyboardInterrupt
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


# --------------------------------------------------------------------------
# what reaches the cache, and when
# --------------------------------------------------------------------------


def test_an_unparsed_page_is_counted_missing_and_not_cached(
    monkeypatch, sleeps, tmp_path
):
    install(monkeypatch, [FakeResponse(200, "<html></html>")])
    cache = tmp_path / "films.json"

    films, missing = enrich(refs_for("xxxx"), cache)

    assert missing == 1
    assert films["xxxx"].status == "unparsed"
    assert load_cache(cache) == {}


def test_an_interrupt_keeps_what_was_already_fetched(monkeypatch, sleeps, tmp_path):
    """Two films fetched, then Ctrl-C: far fewer than SAVE_EVERY, so only the
    final save can have kept them."""
    install(monkeypatch, [FILM, FILM, KeyboardInterrupt()])
    cache = tmp_path / "films.json"

    with pytest.raises(KeyboardInterrupt):
        enrich(refs_for("aaa", "bbb", "ccc"), cache)

    assert set(load_cache(cache)) == {"aaa", "bbb"}


def test_periodic_saves_count_fetched_films_not_position(
    monkeypatch, sleeps, tmp_path
):
    """With SAVE_EVERY of 2 and a refusal first, the first save comes after the
    second *fetched* film (position 3), not at position 2."""
    install(monkeypatch, [FakeResponse(429)] + [FILM] * 4)
    monkeypatch.setattr(enrich_module, "SAVE_EVERY", 2)
    saved: list[int] = []
    real_save = enrich_module.save_cache

    def spy(path, films, stored=None):
        saved.append(sum(1 for info in films.values() if info.status == "ok"))
        real_save(path, films, stored)

    monkeypatch.setattr(enrich_module, "save_cache", spy)

    enrich(refs_for("a1", "a2", "a3", "a4", "a5"), tmp_path / "films.json")

    assert saved[0] == 2


def test_the_cache_file_is_read_once_per_run(monkeypatch, sleeps, tmp_path):
    """Saving merges into the copy already in memory instead of decoding the
    whole file again on every periodic save."""
    install(monkeypatch, [FILM] * 5)
    monkeypatch.setattr(enrich_module, "SAVE_EVERY", 2)
    reads: list[int] = []
    real_load = enrich_module.load_cache

    def counting(path):
        reads.append(1)
        return real_load(path)

    monkeypatch.setattr(enrich_module, "load_cache", counting)

    enrich(refs_for("a1", "a2", "a3", "a4", "a5"), tmp_path / "films.json")

    assert len(reads) == 1


def test_a_run_that_ends_on_a_save_boundary_saves_once_more_not_twice(
    monkeypatch, sleeps, tmp_path
):
    """Three films with SAVE_EVERY at 25: nothing falls on the cadence, so the
    only save is the closing one."""
    install(monkeypatch, [FILM] * 3)
    saves: list[int] = []
    real_save = enrich_module.save_cache

    def spy(path, films, stored=None):
        saves.append(1)
        real_save(path, films, stored)

    monkeypatch.setattr(enrich_module, "save_cache", spy)

    enrich(refs_for("a1", "a2", "a3"), tmp_path / "films.json")

    assert len(saves) == 1


def test_a_run_keeps_cached_films_outside_its_own_group(monkeypatch, sleeps, tmp_path):
    path = tmp_path / "films.json"
    save_cache(path, {"old1": cached_film("old1")})
    install(monkeypatch, [FILM])

    enrich(refs_for("new1"), path)

    assert set(load_cache(path)) == {"old1", "new1"}
