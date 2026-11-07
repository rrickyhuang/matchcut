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
  - Group agreement prefers films every member rated; if under
    `AGREEMENT_MIN_FILMS` qualify it falls back to films at least
    `AGREEMENT_FALLBACK_RATERS` members rated. The report says which.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from .models import RATING_STEPS, Group, Person, Thresholds

AGREEMENT_MIN_FILMS = 20
AGREEMENT_FALLBACK_RATERS = 3

#: Tilt below this is not worth a summary sentence.
TILT_WORTH_MENTIONING = 0.1

HOT_TAKES_PER_SIDE = 4
HOT_TAKE_MIN_OTHERS = 2
CALLING_CARDS_LIMIT = 6
CONSENSUS_LIMIT = 5
TOP_OTHER_LANGUAGES = 5


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------


@dataclass
class PairStats:
    a: str
    b: str
    shared: int
    correlation: float | None
    mean_abs_diff: float | None
    within_half_star: float | None
    library_overlap: float
    low_sample: bool


@dataclass
class PersonStats:
    label: str
    watched: int
    rated: int
    mean_rating: float | None
    spread: float | None
    five_star_count: int
    tilt: float | None
    distribution: dict[float, float]


@dataclass
class FilmLine:
    """One film as the report lists it, with whatever number earned its place."""

    boxd_id: str
    title: str
    year: int | None
    value: float | None = None
    detail: str = ""


@dataclass
class Agreement:
    basis: str
    films_counted: int
    mean_spread: float | None
    unanimous: list[FilmLine] = field(default_factory=list)
    divisive: list[FilmLine] = field(default_factory=list)
    #: Raters a film needed on the fallback basis; fewer than
    #: `AGREEMENT_FALLBACK_RATERS` when the group is smaller than that.
    min_raters: int = AGREEMENT_FALLBACK_RATERS


@dataclass
class Consensus:
    films_counted: int
    favorites: list[FilmLine] = field(default_factory=list)
    lowest: list[FilmLine] = field(default_factory=list)


@dataclass
class ShareRow:
    """One genre, decade or language row: how much, and how well liked."""

    key: str
    share: float
    watched: int
    rated: int
    average: float | None  # None when under `Thresholds.min_group`


@dataclass
class Breakdown:
    per_person: dict[str, list[ShareRow]]
    keys: list[str]
    #: Watched films that had no key at all, so the shares rest on fewer films.
    skipped: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _title(group: Group, boxd_id: str) -> tuple[str, int | None]:
    """Prefer the enriched title, fall back to whatever an export called it."""
    info = group.films.get(boxd_id)
    if info is not None and info.title:
        return info.title, info.year
    for person in group.people:
        ref = person.watched.get(boxd_id) or person.watchlist.get(boxd_id)
        if ref is not None:
            return ref.title, ref.year
    return boxd_id, None


def _line(group: Group, boxd_id: str, value: float | None, detail: str = "") -> FilmLine:
    title, year = _title(group, boxd_id)
    return FilmLine(boxd_id=boxd_id, title=title, year=year, value=value, detail=detail)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, or None when it is undefined.

    It is undefined on fewer than 2 points, and when either person gave every
    shared film the same rating -- that is zero variance, not zero correlation,
    so the report must show nothing rather than 0.00.
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    var_x = sum(d * d for d in dx)
    var_y = sum(d * d for d in dy)
    if var_x == 0 or var_y == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / math.sqrt(var_x * var_y)


def _mean(values) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def _stdev(values: list[float]) -> float | None:
    """Population standard deviation -- the "spread" column."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def raters_by_film(group: Group) -> dict[str, dict[str, float]]:
    """boxd_id -> {label: rating} for every film anyone rated."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for person in group.people:
        for boxd_id, rating in person.ratings.items():
            out[boxd_id][person.label] = rating
    return dict(out)


# --------------------------------------------------------------------------
# Pairs and people
# --------------------------------------------------------------------------


def pair_stats(group: Group, thresholds: Thresholds) -> list[PairStats]:
    """Every unordered pair, in the people's own order."""
    rows: list[PairStats] = []
    for a, b in combinations(group.people, 2):
        shared = sorted(a.rated_ids & b.rated_ids)
        xs = [a.ratings[i] for i in shared]
        ys = [b.ratings[i] for i in shared]

        either = a.watched_ids | b.watched_ids
        overlap = len(a.watched_ids & b.watched_ids) / len(either) if either else 0.0

        diffs = [abs(x - y) for x, y in zip(xs, ys)]
        rows.append(
            PairStats(
                a=a.label,
                b=b.label,
                shared=len(shared),
                correlation=pearson(xs, ys),
                mean_abs_diff=_mean(diffs),
                within_half_star=(
                    sum(1 for d in diffs if d <= 0.5) / len(diffs) if diffs else None
                ),
                library_overlap=overlap,
                low_sample=len(shared) < thresholds.min_overlap,
            )
        )
    return rows


def _tilt(group: Group, person: Person) -> float | None:
    """Mean rating minus the others' mean, over films shared with someone.

    Restricted to shared films so a person is not judged on the taste of the
    films only they have seen.
    """
    others = [p for p in group.people if p.label != person.label]
    mine: list[float] = []
    theirs: list[float] = []
    for boxd_id, rating in person.ratings.items():
        other_ratings = [p.ratings[boxd_id] for p in others if boxd_id in p.ratings]
        if not other_ratings:
            continue
        mine.append(rating)
        theirs.append(sum(other_ratings) / len(other_ratings))
    if not mine:
        return None
    return sum(mine) / len(mine) - sum(theirs) / len(theirs)


def person_stats(group: Group) -> list[PersonStats]:
    rows: list[PersonStats] = []
    for person in group.people:
        ratings = list(person.ratings.values())
        counts = Counter(ratings)
        total = len(ratings)
        rows.append(
            PersonStats(
                label=person.label,
                watched=len(person.watched),
                rated=total,
                mean_rating=_mean(ratings),
                spread=_stdev(ratings),
                five_star_count=counts.get(5.0, 0),
                tilt=_tilt(group, person),
                distribution={
                    step: (counts.get(step, 0) / total if total else 0.0)
                    for step in RATING_STEPS
                },
            )
        )
    return rows


# --------------------------------------------------------------------------
# Group agreement and consensus
# --------------------------------------------------------------------------


def group_agreement(group: Group) -> Agreement:
    """Per-film rating spread, with the basis it had to fall back to.

    The fallback wants `AGREEMENT_FALLBACK_RATERS` raters per film, which a
    pair cannot supply, so a smaller group falls back to as many as it has
    (every member) rather than to an empty pool. The sample is small, and the
    report says how many films it rests on.
    """
    by_film = raters_by_film(group)
    everyone = len(group.people)
    min_raters = min(AGREEMENT_FALLBACK_RATERS, everyone)

    full = {f: r for f, r in by_film.items() if len(r) == everyone}
    basis = "all"
    pool = full
    if len(full) < AGREEMENT_MIN_FILMS:
        pool = {f: r for f, r in by_film.items() if len(r) >= min_raters}
        basis = "three-plus"
    if not pool:
        return Agreement(
            basis=basis, films_counted=0, mean_spread=None, min_raters=min_raters
        )

    spreads = {f: max(r.values()) - min(r.values()) for f, r in pool.items()}

    # Tightest agreement first, best-liked breaking the ties.
    tightest = sorted(
        spreads.items(), key=lambda kv: (kv[1], -_mean(pool[kv[0]].values()))
    )
    widest = sorted(spreads.items(), key=lambda kv: (-kv[1], kv[0]))

    return Agreement(
        basis=basis,
        films_counted=len(pool),
        mean_spread=_mean(spreads.values()),
        min_raters=min_raters,
        unanimous=[
            _line(group, f, _mean(pool[f].values()), f"all within {s:g}")
            for f, s in tightest[:CONSENSUS_LIMIT]
        ],
        divisive=[
            _line(group, f, s, _spread_detail(pool[f]))
            for f, s in widest[:CONSENSUS_LIMIT]
        ],
    )


def _spread_detail(ratings: dict[str, float]) -> str:
    """e.g. `ckhaa 5 vs rkyhuang 1.5` -- who sat at each end."""
    low = min(ratings.items(), key=lambda kv: kv[1])
    high = max(ratings.items(), key=lambda kv: kv[1])
    return f"{high[0]} {high[1]:g} vs {low[0]} {low[1]:g}"


def consensus(group: Group) -> Consensus:
    """Shared favorites and lowest rated, over films everyone rated."""
    by_film = raters_by_film(group)
    everyone = len(group.people)
    full = {f: r for f, r in by_film.items() if len(r) == everyone}
    if not full:
        return Consensus(films_counted=0)

    means = {f: _mean(r.values()) for f, r in full.items()}
    best = sorted(means.items(), key=lambda kv: (-kv[1], kv[0]))
    worst = sorted(means.items(), key=lambda kv: (kv[1], kv[0]))
    return Consensus(
        films_counted=len(full),
        favorites=[_line(group, f, m) for f, m in best[:CONSENSUS_LIMIT]],
        lowest=[_line(group, f, m) for f, m in worst[:CONSENSUS_LIMIT]],
    )


def all_five_stars(group: Group) -> list[FilmLine]:
    """Films every member rated 5. Used by a summary fact."""
    by_film = raters_by_film(group)
    everyone = len(group.people)
    return [
        _line(group, f, 5.0)
        for f, r in sorted(by_film.items())
        if len(r) == everyone and all(v == 5.0 for v in r.values())
    ]


# --------------------------------------------------------------------------
# Hot takes and calling cards
# --------------------------------------------------------------------------


def hot_takes(group: Group) -> dict[str, dict]:
    """Per person: top 4 above and top 4 below the others' mean.

    A film qualifies when the person and at least `HOT_TAKE_MIN_OTHERS` others
    rated it, so one friend's stray rating cannot make a hot take. That rule
    needs 3 people to fire at all, so a pair falls back to 1 other -- which
    makes a "hot take" simply a disagreement, and the report says so.
    """
    min_others = min(HOT_TAKE_MIN_OTHERS, len(group.people) - 1)
    out: dict[str, dict] = {}
    for person in group.people:
        others = [p for p in group.people if p.label != person.label]
        gaps: list[tuple[str, float, float]] = []
        for boxd_id, rating in person.ratings.items():
            other = [p.ratings[boxd_id] for p in others if boxd_id in p.ratings]
            if len(other) < min_others:
                continue
            others_mean = sum(other) / len(other)
            gaps.append((boxd_id, rating - others_mean, others_mean))

        above = sorted((g for g in gaps if g[1] > 0), key=lambda g: (-g[1], g[0]))
        below = sorted((g for g in gaps if g[1] < 0), key=lambda g: (g[1], g[0]))
        out[person.label] = {
            "above": [
                _line(group, f, gap, f"{person.ratings[f]:g} vs {m:.1f}")
                for f, gap, m in above[:HOT_TAKES_PER_SIDE]
            ],
            "below": [
                _line(group, f, gap, f"{person.ratings[f]:g} vs {m:.1f}")
                for f, gap, m in below[:HOT_TAKES_PER_SIDE]
            ],
            "candidates": len(gaps),
            "min_others": min_others,
        }
    return out


def calling_cards(group: Group) -> dict[str, list[FilmLine]]:
    """Per person: their 5-star films no other member has watched.

    Up to `CALLING_CARDS_LIMIT`, most recently logged first.
    """
    out: dict[str, list[FilmLine]] = {}
    for person in group.people:
        seen_by_others: set[str] = set()
        for other in group.people:
            if other.label != person.label:
                seen_by_others |= other.watched_ids

        candidates = [
            boxd_id
            for boxd_id, rating in person.ratings.items()
            if rating == 5.0 and boxd_id not in seen_by_others
        ]
        candidates.sort(key=lambda i: (person.watched_dates.get(i, ""), i), reverse=True)
        out[person.label] = [
            _line(group, i, 5.0, person.watched_dates.get(i, ""))
            for i in candidates[:CALLING_CARDS_LIMIT]
        ]
    return out


# --------------------------------------------------------------------------
# Breakdowns
# --------------------------------------------------------------------------


def _breakdown(group: Group, thresholds: Thresholds, keys_for) -> Breakdown:
    """Share and average per key, per person.

    `keys_for(boxd_id)` returns the keys a film belongs to -- several for
    genres, one for a decade or a language. Films with no key are skipped and
    counted, so a film missing enrichment shrinks the base rather than landing
    in an "unknown" bucket.
    """
    per_person: dict[str, list[ShareRow]] = {}
    skipped: dict[str, int] = {}
    for person in group.people:
        watched_counts: Counter[str] = Counter()
        rated_values: dict[str, list[float]] = defaultdict(list)
        base = 0
        missed = 0
        for boxd_id in person.watched:
            keys = keys_for(boxd_id)
            if not keys:
                missed += 1
                continue
            base += 1
            for key in keys:
                watched_counts[key] += 1
                if boxd_id in person.ratings:
                    rated_values[key].append(person.ratings[boxd_id])

        rows = [
            ShareRow(
                key=key,
                share=count / base if base else 0.0,
                watched=count,
                rated=len(rated_values[key]),
                average=(
                    _mean(rated_values[key])
                    if len(rated_values[key]) >= thresholds.min_group
                    else None
                ),
            )
            for key, count in watched_counts.items()
        ]
        rows.sort(key=lambda r: (-r.share, r.key))
        per_person[person.label] = rows
        skipped[person.label] = missed
    return Breakdown(per_person=per_person, keys=[], skipped=skipped)


def genre_breakdown(group: Group, thresholds: Thresholds) -> Breakdown:
    """Share of watched films per genre. A film can carry several genres, so
    shares do not sum to 1."""

    def keys_for(boxd_id: str) -> list[str]:
        info = group.enriched(boxd_id)
        return list(info.genres) if info else []

    out = _breakdown(group, thresholds, keys_for)
    out.keys = _shared_keys(out.per_person)
    return out


def decade_breakdown(group: Group, thresholds: Thresholds) -> Breakdown:
    """By release decade. Needs no enrichment -- the export carries the year."""
    years: dict[str, int] = {}
    for person in group.people:
        for boxd_id, ref in person.watched.items():
            if ref.year is not None:
                years.setdefault(boxd_id, ref.year)

    def keys_for(boxd_id: str) -> list[str]:
        year = years.get(boxd_id)
        return [f"{(year // 10) * 10}s"] if year is not None else []

    out = _breakdown(group, thresholds, keys_for)
    out.keys = _shared_keys(out.per_person, numeric=True)
    return out


def language_breakdown(group: Group, thresholds: Thresholds) -> Breakdown:
    """By *primary* language only: English, the top other languages, then the
    rest folded into "other"."""

    def keys_for(boxd_id: str) -> list[str]:
        info = group.enriched(boxd_id)
        return [info.primary_language] if info and info.primary_language else []

    full = _breakdown(group, thresholds, keys_for)

    totals: Counter[str] = Counter()
    for rows in full.per_person.values():
        for row in rows:
            if row.key != "English":
                totals[row.key] += row.watched
    top_other = [key for key, _ in totals.most_common(TOP_OTHER_LANGUAGES)]
    keep = ["English", *top_other]

    folded: dict[str, list[ShareRow]] = {}
    for label, rows in full.per_person.items():
        kept = [r for r in rows if r.key in keep]
        rest = [r for r in rows if r.key not in keep]
        if rest:
            kept.append(
                ShareRow(
                    key="other",
                    share=sum(r.share for r in rest),
                    watched=sum(r.watched for r in rest),
                    rated=sum(r.rated for r in rest),
                    average=None,
                )
            )
        kept.sort(key=lambda r: (r.key == "other", -r.share, r.key))
        folded[label] = kept

    return Breakdown(
        per_person=folded,
        keys=[*keep, "other"],
        skipped=full.skipped,
    )


def _shared_keys(
    per_person: dict[str, list[ShareRow]], numeric: bool = False
) -> list[str]:
    """Every key anyone has, ordered for a table the whole group shares."""
    totals: Counter[str] = Counter()
    for rows in per_person.values():
        for row in rows:
            totals[row.key] += row.watched
    keys = list(totals)
    if numeric:
        return sorted(keys, key=lambda k: int(k.rstrip("s")))
    return sorted(keys, key=lambda k: (-totals[k], k))


# --------------------------------------------------------------------------
# Summary facts
# --------------------------------------------------------------------------


def summary_facts(group: Group, thresholds: Thresholds) -> list[str]:
    """Up to 5 deterministic facts, each from a template that fires only when
    its threshold is met. Same input, same sentences -- no AI, no randomness.
    """
    facts: list[str] = []
    pairs = pair_stats(group, thresholds)
    people = person_stats(group)

    scored = [p for p in pairs if p.correlation is not None and not p.low_sample]
    if scored:
        best = max(scored, key=lambda p: (p.correlation, p.shared))
        facts.append(
            f"{best.a} and {best.b} are the closest pair, at "
            f"{best.correlation:.2f} over {best.shared} shared ratings, with "
            f"{best.within_half_star:.0%} of them within half a star."
        )

    facts.extend(_tilt_fact(group, people))

    harsh = _harshest_shared_genre(group, thresholds)
    if harsh:
        facts.append(
            f"Everyone rates {harsh} below their own average, so it is the "
            "group's blind spot."
        )

    by_film = raters_by_film(group)
    everyone = len(group.people)
    all_watched = set.intersection(*(p.watched_ids for p in group.people))
    all_rated = [f for f, r in by_film.items() if len(r) == everyone]
    who = "Both of you have" if everyone == 2 else f"All {everyone} have"
    facts.append(
        f"{who} seen {len(all_watched)} of the same films and rated "
        f"{len(all_rated)} of them."
    )

    fives = all_five_stars(group)
    if fives:
        titles = ", ".join(f.title for f in fives[:3])
        more = f", and {len(fives) - 3} more" if len(fives) > 3 else ""
        facts.append(f"Everyone gave 5 stars to {titles}{more}.")

    return facts[:5]


def _tilt_fact(group: Group, people: list[PersonStats]) -> list[str]:
    """Who sits furthest from the others. A pair needs different wording, since
    with two people one person's tilt is just the other's mirrored."""
    tilts = [p for p in people if p.tilt is not None]
    if not tilts:
        return []

    if len(group.people) == 2:
        a, b = people
        if a.tilt is None or abs(a.tilt) < TILT_WORTH_MENTIONING:
            return []
        higher, lower = (a, b) if a.tilt > 0 else (b, a)
        return [
            f"{higher.label} rates {abs(a.tilt):.2f} stars higher than "
            f"{lower.label} on the films they share."
        ]

    odd = max(tilts, key=lambda p: (abs(p.tilt), p.label))
    if abs(odd.tilt) < TILT_WORTH_MENTIONING:
        return []
    direction = "above" if odd.tilt > 0 else "below"
    return [
        f"{odd.label} sits furthest from everyone else, rating "
        f"{abs(odd.tilt):.2f} stars {direction} the others on the films "
        "they share."
    ]


def _harshest_shared_genre(group: Group, thresholds: Thresholds) -> str | None:
    """A genre every member rates below their own overall average, if any.

    Ties break on the largest total gap, so the sentence is stable.
    """
    breakdown = genre_breakdown(group, thresholds).per_person
    overall = {
        p.label: p.mean_rating for p in person_stats(group) if p.mean_rating is not None
    }
    if len(overall) != len(group.people):
        return None

    gaps: dict[str, float] = {}
    for genre in breakdown[group.people[0].label]:
        key = genre.key
        total = 0.0
        for label, rows in breakdown.items():
            row = next((r for r in rows if r.key == key), None)
            if row is None or row.average is None or row.average >= overall[label]:
                break
            total += overall[label] - row.average
        else:
            gaps[key] = total
    if not gaps:
        return None
    return max(gaps.items(), key=lambda kv: (kv[1], kv[0]))[0]
