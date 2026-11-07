"""Every number in the report.

Pure functions over a `Group`: no fetching, no file access, no formatting.
That is what makes them testable against made-up exports with known answers.

A "shared film" always means a film two people both *rated*. Unrated watched
films count only toward library overlap and the share breakdowns.

Sample-size rules, from the spec:
  - A pair under `Thresholds.min_overlap` shared ratings is still scored, but
    flagged "low sample"; it is never dropped.
  - A genre or decade average needs `Thresholds.min_group` rated films or it is
    withheld rather than shown.
  - Group agreement prefers films every member rated; if under 20 qualify it
    falls back to films at least 3 members rated. The report must say which.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Group, Thresholds


@dataclass
class PairStats:
    """One pair of people, from `Similarity` through `Library overlap`."""

    a: str
    b: str
    shared: int
    correlation: float | None
    mean_abs_diff: float
    within_half_star: float
    library_overlap: float
    low_sample: bool


@dataclass
class PersonStats:
    """The "at a glance" row plus tilt and rating distribution."""

    label: str
    watched: int
    rated: int
    mean_rating: float
    spread: float
    five_star_count: int
    tilt: float
    distribution: dict[float, float]


def pair_stats(group: Group, thresholds: Thresholds) -> list[PairStats]:
    """Every unordered pair, in a stable order."""
    raise NotImplementedError


def person_stats(group: Group) -> list[PersonStats]:
    raise NotImplementedError


def group_agreement(group: Group) -> dict:
    """Per-film rating spread, with the basis used ("all" or "three-plus")."""
    raise NotImplementedError


def consensus(group: Group) -> dict:
    """Shared favorites, lowest rated and biggest splits."""
    raise NotImplementedError


def hot_takes(group: Group) -> dict[str, dict]:
    """Per person: top 4 above and top 4 below the others' mean.

    A film qualifies when the person and at least 2 others rated it.
    """
    raise NotImplementedError


def calling_cards(group: Group) -> dict[str, list]:
    """Per person: up to 6 of their 5-star films no other member has watched,
    most recently logged first."""
    raise NotImplementedError


def genre_breakdown(group: Group, thresholds: Thresholds) -> dict:
    """Share of watched films per genre, and mean rating where the sample
    allows. A film can carry several genres, so shares do not sum to 1."""
    raise NotImplementedError


def decade_breakdown(group: Group, thresholds: Thresholds) -> dict:
    raise NotImplementedError


def language_breakdown(group: Group) -> dict:
    """Share of watched films by *primary* language only, reported as English,
    other, and the top 5 other languages."""
    raise NotImplementedError


def summary_facts(group: Group, thresholds: Thresholds) -> list[str]:
    """Up to 5 deterministic facts, each from a template that fires only when
    its threshold is met. No AI, no randomness: same input, same sentences."""
    raise NotImplementedError
