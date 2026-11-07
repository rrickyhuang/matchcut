"""The two watch-next lists.

From friends' ratings (per person): a film the person has not watched, rated by
at least 2 other members with a mean of 4.5 or higher. Ranked by mean rating,
then by number of raters. Top 10 each.

From watchlists (group): a film on at least 2 members' watchlists that no
member has watched. Ranked by how many watchlists it appears on. Top 15.
A person with no `watchlist.csv` is left out of this list only.
"""

from __future__ import annotations

from .models import Group

MIN_RATERS = 2
MIN_MEAN_RATING = 4.5
PER_PERSON_LIMIT = 10

MIN_WATCHLISTS = 2
WATCHLIST_LIMIT = 15


def from_friends_ratings(group: Group) -> dict[str, list]:
    """Per person, their top `PER_PERSON_LIMIT` candidates."""
    raise NotImplementedError


def from_watchlists(group: Group) -> list:
    """The group's top `WATCHLIST_LIMIT` unwatched shared watchlist films."""
    raise NotImplementedError
