"""The two watch-next lists.

From friends' ratings (per person): a film the person has not watched, rated by
at least `MIN_RATERS` other members with a mean of `MIN_MEAN_RATING` or higher.
Ranked by mean rating, then by number of raters. Top `PER_PERSON_LIMIT` each.

From watchlists (group): a film on at least `MIN_WATCHLISTS` members'
watchlists that no member has watched. Ranked by how many watchlists it appears
on. Top `WATCHLIST_LIMIT`. A person with no `watchlist.csv` is left out of this
list only.

Neither list needs enrichment: the export already carries title and year.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Group

MIN_RATERS = 2
MIN_MEAN_RATING = 4.5
PER_PERSON_LIMIT = 10

MIN_WATCHLISTS = 2
WATCHLIST_LIMIT = 15


@dataclass
class Recommendation:
    boxd_id: str
    title: str
    year: int | None
    #: Mean rating from the people who rated it, or None for a watchlist pick.
    mean_rating: float | None
    #: Who vouched for it -- raters, or the people with it on their watchlist.
    who: list[str] = field(default_factory=list)


@dataclass
class FriendPicks:
    """One person's list, with the rule that produced it."""

    min_raters: int
    items: list[Recommendation] = field(default_factory=list)


def _title(group: Group, boxd_id: str) -> tuple[str, int | None]:
    info = group.films.get(boxd_id)
    if info is not None and info.title:
        return info.title, info.year
    for person in group.people:
        ref = person.watched.get(boxd_id) or person.watchlist.get(boxd_id)
        if ref is not None:
            return ref.title, ref.year
    return boxd_id, None


def from_friends_ratings(group: Group) -> dict[str, FriendPicks]:
    """Per person, their top `PER_PERSON_LIMIT` candidates.

    `MIN_RATERS` needs 3 people to be satisfiable, so a pair falls back to the
    one other person. `FriendPicks.min_raters` records which rule was used, so
    the report can say "rkyhuang rated it 5" rather than imply a consensus.
    """
    min_raters = min(MIN_RATERS, len(group.people) - 1)
    out: dict[str, FriendPicks] = {}

    for person in group.people:
        others = [p for p in group.people if p.label != person.label]
        picks: list[Recommendation] = []

        candidates: set[str] = set()
        for other in others:
            candidates |= other.rated_ids
        candidates -= person.watched_ids

        for boxd_id in candidates:
            raters = [(p.label, p.ratings[boxd_id]) for p in others if boxd_id in p.ratings]
            if len(raters) < min_raters:
                continue
            mean = sum(r for _, r in raters) / len(raters)
            if mean < MIN_MEAN_RATING:
                continue
            title, year = _title(group, boxd_id)
            picks.append(
                Recommendation(
                    boxd_id=boxd_id,
                    title=title,
                    year=year,
                    mean_rating=mean,
                    who=[f"{label} {rating:g}" for label, rating in sorted(raters)],
                )
            )

        picks.sort(key=lambda r: (-r.mean_rating, -len(r.who), r.title))
        out[person.label] = FriendPicks(
            min_raters=min_raters, items=picks[:PER_PERSON_LIMIT]
        )
    return out


def from_watchlists(group: Group) -> list[Recommendation]:
    """The group's top `WATCHLIST_LIMIT` unwatched shared watchlist films."""
    contributors = [p for p in group.people if p.has_watchlist]
    if len(contributors) < MIN_WATCHLISTS:
        return []

    watched_by_anyone: set[str] = set()
    for person in group.people:
        watched_by_anyone |= person.watched_ids

    wanted_by: dict[str, list[str]] = {}
    for person in contributors:
        for boxd_id in person.watchlist:
            if boxd_id in watched_by_anyone:
                continue
            wanted_by.setdefault(boxd_id, []).append(person.label)

    picks: list[Recommendation] = []
    for boxd_id, labels in wanted_by.items():
        if len(labels) < MIN_WATCHLISTS:
            continue
        title, year = _title(group, boxd_id)
        picks.append(
            Recommendation(
                boxd_id=boxd_id,
                title=title,
                year=year,
                mean_rating=None,
                who=sorted(labels),
            )
        )

    picks.sort(key=lambda r: (-len(r.who), r.title))
    return picks[:WATCHLIST_LIMIT]
